"""Pinned genuine Prusa 2.9.7 test of two independently coloured models.

Uses two signed, separately fingerprinted source objects on the same MMU
plate, native T1 paint on the left front and T2 paint on the right back.
Measure actual moving positive-E exterior toolpaths and all three tools'
native wipe-tower purge, not merely successful CLI import.
"""
import hashlib
import math
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

from core.slicer_plate_3mf import _triangles
from core.slicer_native_support_paint import _fingerprint
from core.slicer_prusa_colour_project import build_prusa_multi_colour_candidate
from core.slicer_prusa_wipe_tower import add_prusa_native_wipe_tower
from core.slicer_prusa_filament_palette import compile_prusa_filament_palette
from core.slicer_prusa_process_settings import apply_prusa_process_overrides
from core.slicer_prusa_purge import compile_prusa_purge_matrix
from scripts.prusa_generate_mmu_paint import fixture
from slicer_worker.prusa_vendor_profiles import (
    flatten_prusa_vendor_preset,validate_flat_prusa_preset)
from slicer_worker.prusa_gcode_audit import (
    run_prusa_mmu_with_numeric_recheck,WORD,audit_prusa_positive_e)
from slicer_worker.runner import run_prusa


def audit_regions(raw):
    """Classify 3D toolpaths only when real positive E and XY motion occur."""
    position=[None,None,None]
    active=None
    e=0.
    relative_e=relative_xyz=False
    role=""
    counts={tool:{"left-front":0,"left-back":0,
                  "right-front":0,"right-back":0,"tower":0}
            for tool in (0,1,2)}
    for index,line in enumerate(raw.decode("utf-8").splitlines()):
        if index>2_000_000 or len(line)>16384:
            raise ValueError("Multi-model paint G-code exceeds audit limit.")
        if line.startswith(";TYPE:"):
            role=line.partition(":")[2].strip().lower()
        cmd=line.split(";",1)[0].strip()
        if not cmd:continue
        op=cmd.split(None,1)[0].upper()
        if op.startswith("T") and op[1:].isdigit():
            active=int(op[1:])
            if active not in counts:
                raise ValueError("Unexpected native painted colour tool.")
            continue
        if op not in ("M82","M83","G90","G91","G92",
                      "G0","G00","G1","G01"):
            continue
        words={k.upper():float(v) for k,v in WORD.findall(cmd)}
        if any(not math.isfinite(v) for v in words.values()):
            raise ValueError("Nonfinite native painted colour G-code.")
        if op=="M82":relative_e=False
        elif op=="M83":relative_e=True
        elif op=="G90":relative_xyz=False
        elif op=="G91":relative_xyz=True
        elif op=="G92":
            e=words.get("E",e)
            for i,key in enumerate("XYZ"):
                if key in words:position[i]=words[key]
        else:
            before=tuple(position)
            for i,key in enumerate("XYZ"):
                if key in words:
                    position[i]=(position[i]+words[key] if relative_xyz and
                                 position[i] is not None else None if relative_xyz
                                 else words[key])
            if "E" not in words:continue
            delta=words["E"] if relative_e else words["E"]-e
            e=e+words["E"] if relative_e else words["E"]
            if (delta<=1e-6 or op not in ("G1","G01") or
                    active not in counts or any(n is None for n in before+tuple(position))):
                continue
            middle=tuple((a+b)/2 for a,b in zip(before,position))
            distance=math.hypot(position[0]-before[0],position[1]-before[1])
            if 49<=middle[0]<=120 and 135<=middle[1]<=195:
                counts[active]["tower"]+=1
            if distance<=1e-6 or role!="external perimeter" or not 2<middle[2]<18:
                continue
            for name,x,y in (("left-front",90,95),("left-back",90,115),
                             ("right-front",160,95),("right-back",160,115)):
                if x-11<=middle[0]<=x+11 and abs(middle[1]-y)<1.5:
                    counts[active][name]+=1
    if (counts[1]["left-front"]<30 or counts[2]["right-back"]<30 or
            counts[0]["left-back"]<30 or counts[0]["right-front"]<30 or
            any(counts[t][name]>2 for t,name in (
                (1,"left-back"),(1,"right-front"),(1,"right-back"),
                (2,"left-front"),(2,"left-back"),(2,"right-front"))) or
            any(counts[t]["tower"]<10 for t in (0,1,2))):
        raise AssertionError(("Independent native 3MF MMU paint leakage or missing purges",counts))
    return counts


def main(binary,vendor):
    source=Path(vendor).read_bytes()
    digest=hashlib.sha256(source).hexdigest()
    def preset(kind,name):
        return flatten_prusa_vendor_preset(
            source,kind=kind,name=name,expected_sha256=digest)
    printer=preset("printer","Original Prusa i3 MK3S & MK3S+ MMU3")
    filament=validate_flat_prusa_preset(
        preset("filament","Generic PLA"),kind="filament")
    palette=compile_prusa_filament_palette(printer,[
        "".join(f"{k} = {v}\n" for k,v in sorted({
            **filament,"temperature":str(temp),
            "first_layer_temperature":str(temp)}.items())).encode()
        for temp in (205,210,215,220,225)])
    process=compile_prusa_purge_matrix(
        printer,apply_prusa_process_overrides(
            preset("print","0.20mm NORMAL"),
            {"layer_height":.16,"wall_loops":3}),
        [[0 if a==b else 80 for b in range(5)] for a in range(5)])
    stl,_,_,left_paint=fixture(include_paint=True)
    faces=list(_triangles(stl))
    low=[min(p[i] for face in faces for p in face) for i in range(3)]
    high=[max(p[i] for face in faces for p in face) for i in range(3)]
    centre=((low[0]+high[0])/2,(low[1]+high[1])/2,low[2])
    local=[[tuple(p[i]-centre[i] for i in range(3)) for p in face]
           for face in faces]
    back=[{"face":i,"polygon":[list(p) for p in face]}
          for i,face in enumerate(local)
          if all(abs(p[1]-10)<1e-5 for p in face)]
    if len(back)!=2:
        raise AssertionError("Right independent painted back face missing.")
    right_paint={**left_paint,
                 "signature":_fingerprint(local),
                 "palette":[*left_paint["palette"],{
                     "color":"#fadd4d","label":"T2"}],
                 "regions":[{"slot":2,"patches":back}]}
    rows=[({"asset_id":"left-painted","x_mm":-35,"y_mm":0,
            "z_mm":0,"rotation_deg":0,"scale_percent":100,
            "colour_paint":left_paint},stl),
          ({"asset_id":"right-painted","x_mm":35,"y_mm":0,
            "z_mm":0,"rotation_deg":0,"scale_percent":100,
            "colour_paint":right_paint},stl)]
    project=build_prusa_multi_colour_candidate(
        rows,printer_ini=printer,colour_tool_indices={1:1,2:2},
        bed_width=250,bed_depth=210)
    project=add_prusa_native_wipe_tower(
        project,x_mm=55,y_mm=150,rotation_deg=0,
        bed_width=250,bed_depth=210)
    from slicer_worker.prusa_multi_colour import (
        inspect_prusa_multi_colour,audit_prusa_multi_colour_gcode)
    signed=inspect_prusa_multi_colour(
        project,printer_ini=printer,tower=(55,150,0,250,210))
    if tuple(obj["tool"] for obj in signed)!=(1,2):
        raise AssertionError("Model-local T1/T2 paint identity was not retained.")
    with TemporaryDirectory(prefix="prusa-independent-painted-") as folder:
        work=Path(folder)
        for filename,data in (
                ("input.3mf",project),("printer.ini",printer),
                ("filament.ini",palette),("process.ini",process)):
            (work/filename).write_bytes(data)
        (work/"prusa-offline-colour.marker").write_text("v1")
        _,gcode=run_prusa_mmu_with_numeric_recheck(
            run_prusa,Path(binary),work,timeout_seconds=300,
            max_bytes=64*1024*1024)
        audit_prusa_positive_e(gcode)
        # The fixed public synthetic plate may log its expected regions.
        # Qualify the true native tool separation before any softer
        # source-driven fallback could mask an upstream paint failure.
        direct=audit_regions(gcode)
        print("Native Prusa synthetic two-object colour movements",
              direct,flush=True)
        proof=audit_prusa_multi_colour_gcode(
            gcode,project,printer_ini=printer,tower=(55,150,0,250,210))
        print("PASS: native independent T1/T2 painted ModelParts",
              direct,proof,
              hashlib.sha256(gcode).hexdigest(),flush=True)


if __name__=="__main__":
    main(*sys.argv[1:])
