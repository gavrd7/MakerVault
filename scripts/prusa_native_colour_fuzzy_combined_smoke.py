"""Genuine pinned Prusa 2.9.7 overlapping colour+selective-fuzzy research.

Compare the same painted MMU ModelPart with and without a separate
back-wall fuzzy brush. Native G-code must retain isolated T1 front paint and
show many additional deposited short T0 external paths only on the back.
This experiment does not unlock production mixed paint admission.
"""
import hashlib
import math
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

from core.slicer_plate_3mf import _triangles
from core.slicer_native_support_paint import _fingerprint
from core.slicer_prusa_colour_project import build_prusa_colour_candidate
from core.slicer_prusa_filament_palette import compile_prusa_filament_palette
from core.slicer_prusa_process_settings import apply_prusa_process_overrides
from core.slicer_prusa_purge import compile_prusa_purge_matrix
from core.slicer_prusa_wipe_tower import add_prusa_native_wipe_tower
from scripts.prusa_generate_mmu_paint import fixture
from scripts.prusa_native_five_colour_paint_smoke import painted_external_walls
from slicer_worker.prusa_gcode_audit import (
    run_prusa_mmu_with_numeric_recheck, WORD, audit_prusa_positive_e)
from slicer_worker.prusa_vendor_profiles import (
    flatten_prusa_vendor_preset, validate_flat_prusa_preset)
from slicer_worker.runner import run_prusa


def back_wall_short_external(data):
    """Count only moving, positive-E, short back-wall perimeter G1 paths."""
    xyz=[None,None,None]
    relative_e=relative_xyz=False
    extrusion=0.
    role=""
    back=front=0
    for index,line in enumerate(data.decode("utf-8").splitlines()):
        if index>2_000_000 or len(line)>16384:
            raise ValueError("Prusa coloured fuzz G-code exceeds scan limits.")
        if line.startswith(";TYPE:"):
            role=line.partition(":")[2].strip().lower()
        cmd=line.split(";",1)[0].strip()
        if not cmd:
            continue
        op=cmd.split(None,1)[0].upper()
        if op not in ("M82","M83","G90","G91","G92",
                      "G0","G00","G1","G01"):
            continue
        words={k.upper():float(v) for k,v in WORD.findall(cmd)}
        if any(not math.isfinite(v) or abs(v)>1e9 for v in words.values()):
            raise ValueError("Nonfinite Prusa painted fuzz G-code.")
        if op=="M82": relative_e=False
        elif op=="M83": relative_e=True
        elif op=="G90": relative_xyz=False
        elif op=="G91": relative_xyz=True
        elif op=="G92":
            extrusion=words.get("E",extrusion)
            for i,k in enumerate("XYZ"):
                if k in words: xyz[i]=words[k]
        else:
            before=tuple(xyz)
            for i,k in enumerate("XYZ"):
                if k in words:
                    xyz[i]=(xyz[i]+words[k] if relative_xyz and
                            xyz[i] is not None else None if relative_xyz
                            else words[k])
            if "E" not in words:
                continue
            delta=words["E"] if relative_e else words["E"]-extrusion
            extrusion=extrusion+words["E"] if relative_e else words["E"]
            if (delta<=1e-6 or op not in ("G1","G01") or
                    role!="external perimeter" or
                    any(p is None for p in before+tuple(xyz))):
                continue
            length=math.hypot(xyz[0]-before[0],xyz[1]-before[1])
            midpoint=((xyz[0]+before[0])/2,(xyz[1]+before[1])/2)
            if (.01<=length<=1.25 and 3<=xyz[2]<=18 and
                    110<=midpoint[0]<=140):
                if 113.5<=midpoint[1]<=116.5:
                    back+=1
                if 93.5<=midpoint[1]<=96.5:
                    front+=1
    return back,front


def main(binary,vendor):
    blob=Path(vendor).read_bytes()
    checksum=hashlib.sha256(blob).hexdigest()
    def profile(kind,name):
        return flatten_prusa_vendor_preset(
            blob,kind=kind,name=name,expected_sha256=checksum)
    printer=profile("printer","Original Prusa i3 MK3S & MK3S+ MMU3")
    filament=validate_flat_prusa_preset(
        profile("filament","Generic PLA"),kind="filament")
    profiles=[]
    for temp in (205,210,215,220,225):
        material={**filament,"temperature":str(temp),
                  "first_layer_temperature":str(temp)}
        profiles.append("".join(f"{key} = {value}\n"
                        for key,value in sorted(material.items())).encode())
    palette=compile_prusa_filament_palette(printer,profiles)
    process=apply_prusa_process_overrides(
        profile("print","0.20mm NORMAL"),
        {"layer_height":.16,"wall_loops":3})
    process=compile_prusa_purge_matrix(
        printer,process,[[0 if a==b else 80 for b in range(5)]
                         for a in range(5)])
    source,_,_,paint=fixture(include_paint=True)
    faces=list(_triangles(source))
    low=[min(p[i] for face in faces for p in face) for i in range(3)]
    high=[max(p[i] for face in faces for p in face) for i in range(3)]
    center=((low[0]+high[0])/2,(low[1]+high[1])/2,low[2])
    local=[[tuple(p[i]-center[i] for i in range(3)) for p in face]
           for face in faces]
    back=[{"face":index,"polygon":[list(v) for v in face]}
          for index,face in enumerate(local)
          if all(abs(v[1]-10)<1e-5 for v in face)]
    if len(back)!=2:
        raise AssertionError("Native back-wall fuzzy fixture needs two facets.")
    fuzz={"version":2,"signature":_fingerprint(local),
          "regions":[{"slot":0,"patches":back}]}
    results={}
    with TemporaryDirectory(prefix="prusa-colour-fuzzy-") as folder:
        for name, extra in (("colour",{}),
                            ("colour-fuzzy",{"fuzzy_skin_paint":fuzz})):
            row={"asset_id":"compound-colour-fuzz","x_mm":0,"y_mm":0,
                 "z_mm":0,"rotation_deg":0,"scale_percent":100,
                 "colour_paint":paint,**extra}
            project=build_prusa_colour_candidate(
                row,source,printer_ini=printer,colour_tool_indices={1:1},
                bed_width=250,bed_depth=210,research_compound=bool(extra))
            project=add_prusa_native_wipe_tower(
                project,x_mm=55,y_mm=150,rotation_deg=0,
                bed_width=250,bed_depth=210)
            from slicer_worker.prusa_offline_contract import (
                validate_prusa_offline_colour_inputs)
            signed=validate_prusa_offline_colour_inputs(
                project=project,printer=printer,filament=palette,
                process=process,tool=1,tower=[55,150,0,250,210])
            assert signed["colour_fuzzy"]==bool(extra),signed
            work=Path(folder)/name
            work.mkdir()
            for filename,raw in (
                    ("input.3mf",project),("printer.ini",printer),
                    ("filament.ini",palette),("process.ini",process)):
                (work/filename).write_bytes(raw)
            (work/"prusa-offline-colour.marker").write_text("v1")
            _,gcode=run_prusa_mmu_with_numeric_recheck(
                run_prusa,Path(binary),work,
                timeout_seconds=300,max_bytes=64*1024*1024)
            assert audit_prusa_positive_e(gcode)["positive_e_moves"]>100
            walls=painted_external_walls(gcode)
            if extra:
                from slicer_worker.prusa_colour_fuzzy import audit_prusa_colour_fuzzy_gcode
                proof=audit_prusa_colour_fuzzy_gcode(gcode,project)
                assert proof["fuzzy_back_short_moves"]>100
                print("Prusa signed native mixed colour/fuzzy worker audit",
                      proof,flush=True)
            if walls[1]["front"]<20 or walls[1]["back"]>2:
                raise AssertionError((name,"Native T1 painting changed",walls))
            results[name]=back_wall_short_external(gcode)
            print("Native Prusa colour/fuzzy G-code",name,
                  {"short_back_front":results[name],"T1":walls[1],
                   "sha256":hashlib.sha256(gcode).hexdigest()},flush=True)
    control,combined=results["colour"],results["colour-fuzzy"]
    if (combined[0]<max(80,control[0]*5) or
            combined[1]>max(20,control[1]*1.5)):
        raise AssertionError(
            ("Native Prusa compound colour/fuzzy wall effect not isolated",
             results))
    print("PASS: native colour T1 retained while back-wall selective fuzzy "
          "survives combined 3MF on MMU",flush=True)


if __name__=="__main__":
    main(*sys.argv[1:])
