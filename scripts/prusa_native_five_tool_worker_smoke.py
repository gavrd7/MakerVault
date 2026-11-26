"""Five independent MMU toolpaths: genuine pinned Prusa 2.9.7 research.

This only validates offline G-code, not hardware/printer submission.
"""
import base64
import hashlib
from pathlib import Path
import sys
import tempfile
import uuid

from core.slicer_prusa_multitool_project import build_prusa_multitool_candidate
from core.slicer_prusa_filament_palette import compile_prusa_filament_palette
from core.slicer_prusa_process_settings import apply_prusa_process_overrides
from core.slicer_prusa_purge import compile_prusa_purge_matrix
from core.slicer_prusa_wipe_tower import add_prusa_native_wipe_tower
from core.tests.test_slicer_prusa_plate import cube, item
from slicer_worker.prusa_vendor_profiles import (
    flatten_prusa_vendor_preset,validate_flat_prusa_preset)
from slicer_worker.service import _decode_payload
from slicer_worker.runner import run_prusa
from slicer_worker.prusa_material_gcode_audit import audit_prusa_material_model_gcode


def main(binary,vendor):
    raw=Path(vendor).read_bytes()
    digest=hashlib.sha256(raw).hexdigest()
    printer=flatten_prusa_vendor_preset(
        raw,kind="printer",name="Original Prusa i3 MK3S & MK3S+ MMU3",
        expected_sha256=digest)
    filament=flatten_prusa_vendor_preset(
        raw,kind="filament",name="Generic PLA",expected_sha256=digest)
    process=flatten_prusa_vendor_preset(
        raw,kind="print",name="0.20mm NORMAL",expected_sha256=digest)
    settings=validate_flat_prusa_preset(filament,kind="filament")
    rows=[]
    for index,offset in enumerate((-90,-45,0,45,90)):
        obj=item(x_mm=offset)
        obj["asset_id"]="five-tool-"+str(index)
        if index in (0,1):
            obj["process_overrides"] = {
                "wall_loops": 1 if index == 0 else 5,
                "sparse_infill_density": 23,
            }
        if index in (2,3):
            obj["process_overrides"] = {
                "wall_loops": 3,
                "sparse_infill_density": 10 if index == 2 else 55,
            }
        rows.append((obj,cube(size=8)))
    tools=[1,2,3,4,5]
    project,topology=build_prusa_multitool_candidate(
        rows,printer_ini=printer,tools=tools,bed_width=250,bed_depth=210)
    assert topology["logical_tool_count"]==5
    filaments=[]
    for temp in (205,210,215,220,225):
        settings_copy=dict(settings)
        settings_copy["temperature"]=str(temp)
        settings_copy["first_layer_temperature"]=str(temp)
        filaments.append("".join(f"{k} = {v}\n"
                        for k,v in sorted(settings_copy.items())).encode())
    palette=compile_prusa_filament_palette(printer,filaments)
    process=compile_prusa_purge_matrix(
        printer,process,[[0 if i==j else 80 for j in range(5)] for i in range(5)])
    # Exercise the exact owner-facing native global-setting adapter on
    # genuine five-tool output, not merely independent single-filament CLI.
    process=apply_prusa_process_overrides(process, {
        "layer_height":0.16, "wall_loops":3, "sparse_infill_density":23,
        "top_shell_layers":4, "bottom_shell_layers":4,
    })
    assert b"layer_height = 0.16\n" in process
    assert b"perimeters = 3\n" in process
    assert b"fill_density = 23%\n" in process

    tower=[55,150,0,250,210]
    project=add_prusa_native_wipe_tower(
        project,x_mm=55,y_mm=150,rotation_deg=0,bed_width=250,bed_depth=210)
    encode=lambda data:base64.b64encode(data).decode()
    candidate={
        "job_id":str(uuid.uuid4()),"engine":"prusaslicer",
        "engine_version":"2.9.7","model_format":"3mf",
        "model":encode(project),"printer_profile":encode(printer),
        "filament_profile":encode(palette),"process_profile":encode(process),
        "prusa_offline_mmu":{"tools":tools,"tower":tower}}
    checked=_decode_payload(candidate)
    assert checked["prusa_offline_mmu"]["tools"]==tools
    with tempfile.TemporaryDirectory(prefix="prusa-five-tools-") as temp:
        work=Path(temp)
        for name,data in (("input.3mf",project),("printer.ini",printer),
                          ("filament.ini",palette),("process.ini",process)):
            (work/name).write_bytes(data)
        (work/"prusa-offline-mmu.marker").write_text("v1")
        run_prusa(Path(binary),work)
        output=(work/"output.gcode").read_bytes()
        receipt=audit_prusa_material_model_gcode(
            output,project,printer_ini=printer,tools=tools,tower=tower)
        assert len(receipt["correct_extrusion_moves"])==5
        assert min(receipt["correct_extrusion_moves"])>=20
        assert receipt["incorrect_extrusion_moves"]==[0]*5
        # Native object overrides are qualified by real spatial perimeter
        # deposition, independently of the already-audited selected tools.
        import runpy
        perimeters=runpy.run_path("/tmp/prusa_object_wall.py")[
            "require_distinct_object_wall_counts"](output,project,tools)
        print("Research: Prusa native per-object wall deposition",
              perimeters,flush=True)
        infill=runpy.run_path("/tmp/prusa_object_wall.py")[
            "require_distinct_object_infill"](output,project,tools)
        print("Research: Prusa native per-object sparse infill deposition",
              infill,flush=True)
        assert len(receipt["tower_extrusion_moves"])==5
        print("PASS: five MMU tools selected and deposited correct material on five models",
              receipt,"sha256",hashlib.sha256(output).hexdigest(),flush=True)


if __name__=="__main__":
    main(*sys.argv[1:])
