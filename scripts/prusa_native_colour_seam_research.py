"""Genuine pinned Prusa 2.9.7 MMU colour+seam combined facet research.

Slicer-level paint import is not proof: the same T1 front colour wall must
remain isolated while a separate T0-backed seam enforcer moves the actual
first exterior-wall extrusion toward its signed chosen back face.
This is deliberately research-only until the normal worker can independently
validate simultaneous colour and per-layer seam deposition.
"""
import hashlib
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

from core.slicer_plate_3mf import _triangles
from core.slicer_native_support_paint import _fingerprint
from core.slicer_prusa_colour_project import build_prusa_colour_candidate
from core.slicer_prusa_wipe_tower import add_prusa_native_wipe_tower
from core.slicer_prusa_filament_palette import compile_prusa_filament_palette
from core.slicer_prusa_process_settings import (
    apply_prusa_process_overrides,qualify_prusa_seam_process)
from core.slicer_prusa_purge import compile_prusa_purge_matrix
from core.slicer_prusa_seam_audit import audit_prusa_seam_enforcer_gcode
from scripts.prusa_generate_mmu_paint import fixture
from scripts.prusa_native_five_colour_paint_smoke import painted_external_walls
from slicer_worker.prusa_vendor_profiles import (
    flatten_prusa_vendor_preset,validate_flat_prusa_preset)
from slicer_worker.prusa_gcode_audit import (
    run_prusa_mmu_with_numeric_recheck,audit_prusa_positive_e)
from slicer_worker.runner import run_prusa


def main(binary,vendor):
    source=Path(vendor).read_bytes()
    digest=hashlib.sha256(source).hexdigest()
    def preset(kind,name):
        return flatten_prusa_vendor_preset(
            source,kind=kind,name=name,expected_sha256=digest)
    printer=preset("printer","Original Prusa i3 MK3S & MK3S+ MMU3")
    material=validate_flat_prusa_preset(
        preset("filament","Generic PLA"),kind="filament")
    filaments=[]
    for temperature in (205,210,215,220,225):
        choices={**material,"temperature":str(temperature),
                 "first_layer_temperature":str(temperature)}
        filaments.append("".join(
            f"{key} = {value}\n"
            for key,value in sorted(choices.items())).encode())
    palette=compile_prusa_filament_palette(printer,filaments)
    process=apply_prusa_process_overrides(
        qualify_prusa_seam_process(
            preset("print","0.20mm NORMAL"),"random"),
        {"layer_height":.16,"wall_loops":3})
    process=compile_prusa_purge_matrix(
        printer,process,[[0 if i==j else 80 for j in range(5)]
                         for i in range(5)])
    stl,_,_,paint=fixture(include_paint=True)
    faces=list(_triangles(stl))
    low=[min(p[i] for face in faces for p in face) for i in range(3)]
    high=[max(p[i] for face in faces for p in face) for i in range(3)]
    centre=((low[0]+high[0])/2,(low[1]+high[1])/2,low[2])
    local=[[tuple(p[i]-centre[i] for i in range(3)) for p in face]
           for face in faces]
    back=[{"face":i,"polygon":[list(p) for p in face]}
          for i,face in enumerate(local)
          if all(abs(p[1]-10)<.00001 for p in face)]
    if len(back)!=2:
        raise AssertionError("Expected exactly two native back-wall triangles.")
    seam={"version":2,"signature":_fingerprint(local),
          "regions":[{"slot":0,"patches":back}]}
    base={"asset_id":"colour-seam-native","x_mm":0,"y_mm":0,"z_mm":0,
          "rotation_deg":0,"scale_percent":100,
          "colour_paint":paint}
    results={}
    with TemporaryDirectory(prefix="prusa-colour-seam-") as dirname:
        for label,add in (("colour",{}),
                          ("colour-seam",{"seam_paint":seam})):
            row={**base,**add}
            project=build_prusa_colour_candidate(
                row,stl,printer_ini=printer,colour_tool_indices={1:1},
                bed_width=250,bed_depth=210,
                research_compound=bool(add))
            project=add_prusa_native_wipe_tower(
                project,x_mm=55,y_mm=150,rotation_deg=0,
                bed_width=250,bed_depth=210)
            folder=Path(dirname)/label
            folder.mkdir()
            for filename,content in (("input.3mf",project),
                                      ("printer.ini",printer),
                                      ("filament.ini",palette),
                                      ("process.ini",process)):
                (folder/filename).write_bytes(content)
            (folder/"prusa-offline-colour.marker").write_text("v1")
            _,data=run_prusa_mmu_with_numeric_recheck(
                run_prusa,Path(binary),folder,timeout_seconds=300,
                max_bytes=64*1024*1024)
            audit_prusa_positive_e(data)
            wall=painted_external_walls(data)
            if wall[1]["front"]<20 or wall[1]["back"]>2:
                raise AssertionError(
                    ("Prusa combined seam dropped native colour",label,wall))
            try:
                seam_receipt=audit_prusa_seam_enforcer_gcode(
                    data,{**base,"seam_paint":seam},
                    bed_width=250,bed_depth=210)
            except ValueError as exc:
                seam_receipt={"unqualified":str(exc)}
            results[label]=(wall[1],seam_receipt)
            print("Prusa native colour/seam spatial result",
                  label,results[label],
                  hashlib.sha256(data).hexdigest(),flush=True)
    combined=results["colour-seam"][1]
    if (combined.get("sampled_layers",0)<5 or
            combined.get("matching_layers",0)<5 or
            combined["matching_layers"]<
                .75*combined["sampled_layers"]):
        raise AssertionError(
            ("Native Prusa simultaneous colour/seam did not move actual "
             "first exterior walls to the selected face",results))
    print("PASS: native MMU T1 front colour and opposite signed T0 seam "
          "coexist in genuine positive-E G-code",results,flush=True)


if __name__=="__main__":
    main(*sys.argv[1:])
