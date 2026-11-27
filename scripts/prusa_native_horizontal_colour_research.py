"""Offline research: genuine Prusa XL5 split horizontal top-skin colour.

This fixture is not production admission. It measures real top infill and
wall extrusion per tool before extending spatial TriangleSelector auditing.
"""
import hashlib
import io
import math
import sys
import zipfile
from pathlib import Path
from tempfile import TemporaryDirectory

from defusedxml import ElementTree as SafeET
from core.slicer_plate_3mf import _triangles, NS
from core.slicer_native_support_paint import _fingerprint
from core.slicer_prusa_colour_project import build_prusa_colour_candidate
from core.slicer_prusa_filament_palette import compile_prusa_filament_palette
from core.slicer_prusa_process_settings import apply_prusa_process_overrides
from scripts.prusa_generate_mmu_paint import fixture
from slicer_worker.prusa_vendor_profiles import (
    flatten_prusa_vendor_preset, validate_flat_prusa_preset)
from slicer_worker.prusa_colour_gcode_audit import WORD
from slicer_worker.runner import run_prusa


def _inside(pt, tri):
    a, b, c = tri
    den = (b[1]-c[1])*(a[0]-c[0])+(c[0]-b[0])*(a[1]-c[1])
    if abs(den) < 1e-9:
        return False
    p = ((b[1]-c[1])*(pt[0]-c[0])+(c[0]-b[0])*(pt[1]-c[1]))/den
    q = ((c[1]-a[1])*(pt[0]-c[0])+(a[0]-c[0])*(pt[1]-c[1]))/den
    return min(p,q,1-p-q) > .05


def main(binary, vendor):
    blob = Path(vendor).read_bytes()
    sha = hashlib.sha256(blob).hexdigest()
    def get(kind,name):
        return flatten_prusa_vendor_preset(
            blob,kind=kind,name=name,expected_sha256=sha)
    printer = get("printer","Original Prusa XL - 5T 0.4 nozzle")
    printer = b"\n".join(
        b"binary_gcode = 0" if line.split(b"=",1)[0].strip()==b"binary_gcode"
        else line for line in printer.splitlines()) + b"\n"
    material = validate_flat_prusa_preset(
        get("filament","Generic PLA"),kind="filament")
    filaments=[]
    for temp in (205,210,215,220,225):
        profile = {**material,"temperature":str(temp),
                   "first_layer_temperature":str(temp)}
        filaments.append("".join(f"{k} = {v}\n"
                         for k,v in sorted(profile.items())).encode())
    filament=compile_prusa_filament_palette(printer,filaments)
    settings=validate_flat_prusa_preset(
        get("print","0.20mm NORMAL"),kind="print")
    for k in ("wipe_tower","wipe_into_infill","wipe_into_objects"):
        settings[k]="0"
    process=apply_prusa_process_overrides(
        "".join(f"{k} = {v}\n" for k,v in sorted(settings.items())).encode(),
        {"layer_height":.16,"wall_loops":3})
    stl,_,_,paint=fixture(include_paint=True)
    faces=list(_triangles(stl))
    low=[min(p[a] for face in faces for p in face) for a in range(3)]
    high=[max(p[a] for face in faces for p in face) for a in range(3)]
    origin=((low[0]+high[0])/2,(low[1]+high[1])/2,low[2])
    local=[[tuple(p[a]-origin[a] for a in range(3)) for p in face]
           for face in faces]
    target=next(i for i,face in enumerate(local)
                if all(abs(p[2]-(high[2]-low[2]))<1e-5 for p in face))
    a,b,c=local[target]
    brush=[list(a),[(a[i]+b[i])/2 for i in range(3)],
           [(a[i]+c[i])/2 for i in range(3)]]
    paint={**paint,"signature":_fingerprint(local),
           "regions":[{"slot":1,
                       "patches":[{"face":target,"polygon":brush}]}]}
    project=build_prusa_colour_candidate(
        {"asset_id":"top-skin-brush","x_mm":0,"y_mm":0,
         "z_mm":0,"rotation_deg":0,"scale_percent":100,
         "colour_paint":paint},
        stl,printer_ini=printer,colour_tool_indices={1:1},
        bed_width=360,bed_depth=360)
    with zipfile.ZipFile(io.BytesIO(project)) as z:
        root=SafeET.fromstring(z.read("3D/3dmodel.model"))
    points=[tuple(float(v.get(k)) for k in ("x","y","z"))
            for v in root.findall(
                "./{"+NS+"}resources/{"+NS+"}object/{"+NS+"}mesh/{"+NS+"}vertices/{"+NS+"}vertex")]
    painted=[]
    namespace="{http://schemas.slic3r.org/3mf/2017/06}mmu_segmentation"
    for face in root.findall(
            "./{"+NS+"}resources/{"+NS+"}object/{"+NS+"}mesh/{"+NS+"}triangles/{"+NS+"}triangle"):
        if face.get(namespace)=="8":
            painted.append(tuple((points[int(face.get(key))][0],
                                  points[int(face.get(key))][1])
                                 for key in ("v1","v2","v3")))
    if not painted:
        raise AssertionError("No native horizontal colour facets")
    top=max(p[2] for p in points)
    counts={0:{"painted":0,"top_other":0,"other":0},
            1:{"painted":0,"top_other":0,"other":0}}
    with TemporaryDirectory(prefix="prusa-horizontal-colour-") as directory:
        work=Path(directory)
        for name,body in (("input.3mf",project),("printer.ini",printer),
                          ("filament.ini",filament),("process.ini",process)):
            (work/name).write_bytes(body)
        (work/"prusa-offline-xl-colour.marker").write_text("v1")
        run_prusa(Path(binary),work)
        data=(work/"output.gcode").read_bytes()
        role=""
        tool=None
        position=[None,None,None]
        extruder=0.
        relative_e=relative_xyz=False
        for raw in data.decode("utf-8").splitlines():
            if raw.startswith(";TYPE:"):
                role=raw.partition(":")[2].strip().lower()
            cmd=raw.split(";",1)[0].strip()
            if not cmd:
                continue
            op=cmd.split(None,1)[0].upper()
            if op.startswith("T") and op[1:].isdigit():
                tool=int(op[1:])
                continue
            if op not in ("M82","M83","G90","G91","G92",
                          "G0","G00","G1","G01"):
                continue
            fields={k.upper():float(v) for k,v in WORD.findall(cmd)}
            if op=="M82": relative_e=False
            elif op=="M83": relative_e=True
            elif op=="G90": relative_xyz=False
            elif op=="G91": relative_xyz=True
            elif op=="G92":
                extruder=fields.get("E",extruder)
                for i,k in enumerate("XYZ"):
                    if k in fields: position[i]=fields[k]
            else:
                before=tuple(position)
                for i,k in enumerate("XYZ"):
                    if k in fields:
                        position[i]=(position[i]+fields[k] if relative_xyz and
                                     position[i] is not None else
                                     None if relative_xyz else fields[k])
                if "E" not in fields: continue
                delta=fields["E"] if relative_e else fields["E"]-extruder
                extruder=extruder+fields["E"] if relative_e else fields["E"]
                if (tool not in counts or op not in ("G1","G01")
                        or delta<=1e-6 or any(x is None for x in before+tuple(position))
                        or abs(position[0]-before[0])+abs(position[1]-before[1])<=1e-5):
                    continue
                if abs(position[2]-top)<.7 and "solid infill" in role or (
                        abs(position[2]-top)<.7 and "external perimeter" in role):
                    xy=((position[0]+before[0])/2,
                        (position[1]+before[1])/2)
                    if any(_inside(xy,triangle) for triangle in painted):
                        counts[tool]["painted"]+=1
                    else:
                        counts[tool]["top_other"]+=1
                else:
                    counts[tool]["other"]+=1
        print("Prusa horizontal split colour observed native positive-E",
              counts,"painted triangles",len(painted),
              "sha256",hashlib.sha256(data).hexdigest(),flush=True)
        if counts[1]["painted"] < 8 or counts[0]["top_other"] < 8:
            raise AssertionError(
                "Native partial top-skin colour deposition not demonstrated")
        if counts[1]["top_other"]>max(10,counts[1]["painted"]//4):
            raise AssertionError("Alternate tool leaked beyond top-skin brush")
        print("PASS: horizontal partial brush native colour feasibility",
              flush=True)


if __name__=="__main__":
    main(*sys.argv[1:])
