"""Native Prusa 2.9.7 arbitrary curved, partly split colour surface research.

A 64-segment upright cylinder has a coherent colour brush across several
independent curved exterior facets plus one partial source triangle. Require
actual T1/T0 exterior moving deposition in the correct angular sector.
This is not production admission until the signed per-triangle spatial
worker auditor reproduces the same attribution.
"""
import hashlib
import math
import struct
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

from core.slicer_plate_3mf import _triangles
from core.slicer_native_support_paint import _fingerprint
from core.slicer_prusa_colour_project import build_prusa_colour_candidate
from core.slicer_prusa_filament_palette import compile_prusa_filament_palette
from core.slicer_prusa_process_settings import apply_prusa_process_overrides
from slicer_worker.prusa_vendor_profiles import (
    flatten_prusa_vendor_preset,validate_flat_prusa_preset)
from slicer_worker.prusa_gcode_audit import WORD,audit_prusa_positive_e
from slicer_worker.runner import run_prusa


def cylinder_stl(n=64,radius=10,height=20):
    if n<16:raise ValueError("Insufficient curved source segments.")
    raw=bytearray(b"Prusa signed partial cylindrical paint".ljust(80,b"\0"))
    faces=[]
    centre_bottom=(0.,0.,0.)
    centre_top=(0.,0.,height)
    points=[(radius*math.cos(i*2*math.pi/n),
             radius*math.sin(i*2*math.pi/n)) for i in range(n)]
    for i in range(n):
        j=(i+1)%n
        a=(points[i][0],points[i][1],0.)
        b=(points[j][0],points[j][1],0.)
        c=(points[i][0],points[i][1],height)
        d=(points[j][0],points[j][1],height)
        faces.extend(((a,b,d),(a,d,c),(centre_bottom,b,a),
                      (centre_top,c,d)))
    raw.extend(struct.pack("<I",len(faces)))
    for face in faces:
        raw.extend(struct.pack("<12fH",0,0,0,
                   *(v for point in face for v in point),0))
    return bytes(raw)


def mask_for(stl):
    raw=list(_triangles(stl))
    bounds=[(min(p[i] for t in raw for p in t),
             max(p[i] for t in raw for p in t)) for i in range(3)]
    origin=((bounds[0][0]+bounds[0][1])/2,
            (bounds[1][0]+bounds[1][1])/2,
            bounds[2][0])
    local=[[tuple(p[i]-origin[i] for i in range(3)) for p in face]
           for face in raw]
    patches=[]
    partially_painted=0
    for index,face in enumerate(local):
        if max(v[2] for v in face)-min(v[2] for v in face)<10:
            continue
        middle=(sum(p[0] for p in face)/3,sum(p[1] for p in face)/3)
        angle=math.atan2(middle[1],middle[0])
        if abs(angle)<math.pi/4-.01:
            patches.append({"face":index,"polygon":[list(p) for p in face]})
        elif not partially_painted and math.pi/4<=angle<math.pi/4+.15:
            a,b,c=face
            patches.append({"face":index,"polygon":[
                list(a),[(a[k]+b[k])/2 for k in range(3)],
                [(a[k]+c[k])/2 for k in range(3)]]})
            partially_painted+=1
    if len(patches)<15 or partially_painted!=1:
        raise AssertionError(("Curved colour fixture has no split native facet",
                              len(patches),partially_painted))
    return {"version":2,"signature":_fingerprint(local),
            "palette":[{"color":"#ff8000","label":"Base"},
                       {"color":"#3ec0ff","label":"Curved T1"}],
            "regions":[{"slot":1,"patches":patches}]}


def deposited_sectors(data,*,center=(180.,180.)):
    tool=None
    role=""
    e=0.
    rel_e=rel_xyz=False
    position=[None,None,None]
    counts={0:{"paint":0,"plain":0},
            1:{"paint":0,"plain":0}}
    for line in data.decode("utf-8").splitlines():
        if line.startswith(";TYPE:"):
            role=line.partition(":")[2].strip().lower()
        cmd=line.split(";",1)[0].strip()
        if not cmd:continue
        op=cmd.split(None,1)[0].upper()
        if op.startswith("T") and op[1:].isdigit():
            tool=int(op[1:])
            if tool not in counts:raise ValueError("Unknown curved colour tool.")
            continue
        if op not in ("M82","M83","G90","G91","G92",
                      "G0","G00","G1","G01"):
            continue
        words={k.upper():float(v) for k,v in WORD.findall(cmd)}
        if op=="M82":rel_e=False
        elif op=="M83":rel_e=True
        elif op=="G90":rel_xyz=False
        elif op=="G91":rel_xyz=True
        elif op=="G92":
            e=words.get("E",e)
            for i,key in enumerate("XYZ"):
                if key in words:position[i]=words[key]
        else:
            before=tuple(position)
            for i,key in enumerate("XYZ"):
                if key in words:
                    position[i]=(position[i]+words[key] if rel_xyz and
                                 position[i] is not None else None if rel_xyz
                                 else words[key])
            if "E" not in words:continue
            delta=words["E"] if rel_e else words["E"]-e
            e=e+words["E"] if rel_e else words["E"]
            if (tool not in counts or delta<=1e-6 or
                    op not in ("G1","G01") or role!="external perimeter" or
                    any(p is None for p in before+tuple(position))):
                continue
            x=(before[0]+position[0])/2-center[0]
            y=(before[1]+position[1])/2-center[1]
            z=position[2]
            radius=math.hypot(x,y)
            if not 4<=z<=17 or not 8<=radius<=11:
                continue
            theta=abs(math.atan2(y,x))
            if theta<math.pi/5:
                counts[tool]["paint"]+=1
            elif theta>math.pi/2:
                counts[tool]["plain"]+=1
    if (counts[1]["paint"]<20 or counts[0]["plain"]<30 or
            counts[1]["plain"]>max(2,counts[1]["paint"]//30)):
        raise AssertionError(("Curved native T0/T1 deposition unqualified",counts))
    return counts


def main(binary,vendor):
    blob=Path(vendor).read_bytes()
    digest=hashlib.sha256(blob).hexdigest()
    def preset(kind,name):
        return flatten_prusa_vendor_preset(
            blob,kind=kind,name=name,expected_sha256=digest)
    printer=preset("printer","Original Prusa XL - 5T 0.4 nozzle")
    printer=b"\n".join(
        b"binary_gcode = 0" if line.split(b"=",1)[0].strip()==b"binary_gcode"
        else line for line in printer.splitlines())+b"\n"
    filament=validate_flat_prusa_preset(
        preset("filament","Generic PLA"),kind="filament")
    palette=compile_prusa_filament_palette(printer,[
        "".join(f"{k} = {v}\n" for k,v in sorted({
            **filament,"temperature":str(t),
            "first_layer_temperature":str(t)}.items())).encode()
        for t in (205,210,215,220,225)])
    settings=validate_flat_prusa_preset(
        preset("print","0.20mm NORMAL"),kind="print")
    for key in ("wipe_tower","wipe_into_infill","wipe_into_objects"):
        settings[key]="0"
    process=apply_prusa_process_overrides(
        "".join(f"{key} = {v}\n"
                for key,v in sorted(settings.items())).encode(),
        {"layer_height":.16,"wall_loops":3})
    mesh=cylinder_stl()
    paint=mask_for(mesh)
    project=build_prusa_colour_candidate(
        {"asset_id":"curved-brush","x_mm":0,"y_mm":0,
         "z_mm":0,"rotation_deg":0,"scale_percent":100,
         "colour_paint":paint},
        mesh,printer_ini=printer,colour_tool_indices={1:1},
        bed_width=360,bed_depth=360)
    with TemporaryDirectory(prefix="prusa-curved-paint-") as folder:
        root=Path(folder)
        for name,data in (("input.3mf",project),("printer.ini",printer),
                          ("filament.ini",palette),("process.ini",process)):
            (root/name).write_bytes(data)
        (root/"prusa-offline-xl-colour.marker").write_text("v1")
        run_prusa(Path(binary),root,timeout_seconds=300)
        gcode=(root/"output.gcode").read_bytes()
        audit_prusa_positive_e(gcode)
        proof=deposited_sectors(gcode)
        print("PASS: native Prusa nonplanar multi-facet and partial-triangle "
              "curved paint deposition",proof,
              hashlib.sha256(gcode).hexdigest(),flush=True)


if __name__=="__main__":
    main(*sys.argv[1:])
