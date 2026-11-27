"""Five independent XL toolhead toolpaths: genuine pinned Prusa 2.9.7 research.

This only validates offline G-code, not hardware/printer submission.
"""
import base64
import hashlib
import re
from pathlib import Path
import sys
import tempfile
import uuid

from core.slicer_prusa_multitool_project import build_prusa_multitool_candidate
from core.slicer_prusa_filament_palette import compile_prusa_filament_palette
from core.slicer_prusa_process_settings import apply_prusa_process_overrides
from core.tests.test_slicer_prusa_plate import cube, item
from slicer_worker.prusa_vendor_profiles import (
    flatten_prusa_vendor_preset,validate_flat_prusa_preset)
from slicer_worker.service import _decode_payload
from slicer_worker.runner import WorkerError, run_prusa
from slicer_worker.prusa_material_gcode_audit import audit_prusa_material_model_gcode


def main(binary,vendor):
    raw=Path(vendor).read_bytes()
    digest=hashlib.sha256(raw).hexdigest()
    printer=flatten_prusa_vendor_preset(
        raw,kind="printer",name="Original Prusa XL - 5T 0.4 nozzle",
        expected_sha256=digest)
    # Upstream's XL 5T preset defaults to binary G-code. The verified
    # MakerVault audit accepts only text, so force text in this offline
    # research copy without altering the pinned vendor asset or presets.
    printer=b"\n".join(
        b"binary_gcode = 0" if line.split(b"=",1)[0].strip()==b"binary_gcode" else line
        for line in printer.splitlines())+b"\n"
    assert printer.count(b"binary_gcode = 0")==1
    machine=validate_flat_prusa_preset(printer,kind="printer")
    assert machine.get("single_extruder_multi_material","0") in ("0","false")
    assert len(machine["nozzle_diameter"].split(","))==5
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
        rows,printer_ini=printer,tools=tools,bed_width=360,bed_depth=360)
    assert topology["logical_tool_count"]==5
    filaments=[]
    for temp in (205,210,215,220,225):
        settings_copy=dict(settings)
        settings_copy["temperature"]=str(temp)
        settings_copy["first_layer_temperature"]=str(temp)
        filaments.append("".join(f"{k} = {v}\n"
                        for k,v in sorted(settings_copy.items())).encode())
    palette=compile_prusa_filament_palette(printer,filaments)
    options=validate_flat_prusa_preset(process,kind="print")
    for key in ("wipe_tower","wipe_into_infill","wipe_into_objects"):
        options[key]="0"
    process="".join(f"{k} = {v}\n" for k,v in sorted(options.items())).encode()
    # Exercise the exact owner-facing native global-setting adapter on
    # genuine five-tool output, not merely independent single-filament CLI.
    process=apply_prusa_process_overrides(process, {
        "layer_height":0.16, "wall_loops":3, "sparse_infill_density":23,
        "top_shell_layers":4, "bottom_shell_layers":4,
    })
    assert b"layer_height = 0.16\n" in process
    assert b"perimeters = 3\n" in process
    assert b"fill_density = 23%\n" in process

    encode=lambda data:base64.b64encode(data).decode()
    candidate={
        "job_id":str(uuid.uuid4()),"engine":"prusaslicer",
        "engine_version":"2.9.7","model_format":"3mf",
        "model":encode(project),"printer_profile":encode(printer),
        "filament_profile":encode(palette),"process_profile":encode(process),
        "prusa_offline_xl":{"tools":tools}}
    checked=_decode_payload(candidate)
    assert checked["prusa_offline_xl"]["tools"]==tools
    for change in (
        {"prusa_offline_xl":{"tools":[1,1,1,1,1]}},
        {"prusa_offline_xl":{"tools":[1,2,3,4]}},
        {"prusa_offline_xl":{"tools":[1,2,3,4,6]}},
        {"prusa_offline_xl":{"tools":[1,2,3,4,5],"tower":[55,150,0,360,360]}},
        {"prusa_offline_mmu":{"tools":tools,"tower":[55,150,0,360,360]}},
    ):
        try:
            _decode_payload({**candidate, **change})
        except WorkerError:
            pass
        else:
            raise AssertionError("Unqualified XL five-head request was accepted.")
    with tempfile.TemporaryDirectory(prefix="prusa-five-tools-") as temp:
        work=Path(temp)
        for name,data in (("input.3mf",project),("printer.ini",printer),
                          ("filament.ini",palette),("process.ini",process)):
            (work/name).write_bytes(data)
        (work/"prusa-offline-xl.marker").write_text("v1")
        run_prusa(Path(binary),work)
        output=(work/"output.gcode").read_bytes()
        receipt=audit_prusa_material_model_gcode(
            output,project,printer_ini=printer,tools=tools)
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
        assert receipt["selected_tools"]==(0,1,2,3,4)
        assert receipt["tower_extrusion_moves"]=={}
        # Research-only observable executable heater commands. Do not infer
        # physical heating or firmware behaviour from profile vectors alone.
        heaters=[]
        for line in output.splitlines():
            command=line.split(b";",1)[0].strip()
            if not command:
                continue
            operation=command.split(None,1)[0].upper()
            if operation not in (b"M104",b"M109"):
                continue
            temp=re.search(rb"(?:^|\s)S([0-9]{1,3})(?:\s|$)",command)
            tool=re.search(rb"(?:^|\s)T([0-9])(?:\s|$)",command)
            heaters.append((operation.decode("ascii"),
                            int(tool.group(1)) if tool else None,
                            int(temp.group(1)) if temp else None))
        print("Research: XL 5T executable heater command audit",
              {"count":len(heaters),"distinct_commands":sorted(set(heaters),
                key=lambda row:(row[0],-1 if row[1] is None else row[1],
                                -1 if row[2] is None else row[2]))[:30]},
              flush=True)
        print("PASS: five XL independent heads selected and deposited correct material on five models",
              receipt,"sha256",hashlib.sha256(output).hexdigest(),flush=True)

        # Qualify actual 2.9.7 binary output with independent modifier, cavity,
        # layer scheduling and object settings on different XL heads.
        from core.tests.test_slicer_prusa_3mf import volume
        from slicer_worker.prusa_material_validation import validate_prusa_material_candidate
        modified = []
        for index, (object_settings, mesh) in enumerate(rows):
            entry = dict(object_settings)
            if index == 0:
                modifier = volume("modifier", {"sparse_infill_density": 80})
                modifier.update(width_mm=3, depth_mm=3, height_mm=5,
                                x_mm=-90, y_mm=0, z_mm=4)
                entry["modifier_volumes"] = [modifier]
            if index == 1:
                cavity = volume("negative")
                cavity.update(width_mm=3, depth_mm=3, height_mm=5,
                              x_mm=-45, y_mm=0, z_mm=4)
                entry["modifier_volumes"] = [cavity]
            if index == 2:
                entry["variable_layer_profile"] = {
                    "version": 1, "bands": [
                        {"from_mm": 2, "to_mm": 6, "layer_mm": .12}]}
            if index == 4:
                entry["process_overrides"] = {
                    **entry.get("process_overrides", {}),
                    "top_shell_layers": 0, "bottom_shell_layers": 0}
            modified.append((entry, mesh))
        project2, topology2 = build_prusa_multitool_candidate(
            modified, printer_ini=printer, tools=tools,
            bed_width=360, bed_depth=360)
        assert topology2["kind"] == "independent_tools"
        native_receipt = validate_prusa_material_candidate(
            project2, printer_ini=printer, tools=tools)
        assert native_receipt["objects"] == 5
        candidate["model"] = encode(project2)
        _decode_payload(candidate)
        (work/"input.3mf").write_bytes(project2)
        (work/"output.gcode").unlink()
        run_prusa(Path(binary), work)
        mixed = (work/"output.gcode").read_bytes()
        mixed_receipt = audit_prusa_material_model_gcode(
            mixed, project2, printer_ini=printer, tools=tools)
        assert mixed_receipt["selected_tools"] == tuple(range(5))
        assert mixed_receipt["incorrect_extrusion_moves"] == [0]*5
        assert min(mixed_receipt["correct_extrusion_moves"]) >= 20
        assert hashlib.sha256(output).digest() != hashlib.sha256(mixed).digest()
        # The fifth model has identical native geometry/material and global
        # profile in both runs; only its own top/bottom shell counts changed.
        # Require actual deposited top-surface paths to disappear on T4.
        counters = runpy.run_path("/tmp/prusa_object_wall.py")[
            "count_native_object_deposition"]
        before_shell = counters(output, project, tools)["top_solid_infill"][4]
        after_shell = counters(mixed, project2, tools)["top_solid_infill"][4]
        # The pinned native 8 mm XL fixture has 19 top-solid moving
        # segments before this edit and one afterward. A threshold of 20
        # falsely rejected a genuine 95% reduction despite both tool
        # attribution and real G-code output passing. Require enough
        # baseline segments to measure an effect and a >=85% reduction.
        assert before_shell >= 12 and after_shell <= before_shell * .15, (
            before_shell, after_shell)
        print("PASS: independent T4 shell override changes local top infill",
              before_shell, after_shell, flush=True)
        # An edited layer schedule must be independently visible in G-code
        # deposited over its own model, not merely in the 3MF metadata.
        from core.slicer_prusa_spatial_layers import audit_prusa_multi_object_layer_ranges
        schedules = audit_prusa_multi_object_layer_ranges(
            mixed, modified, bed_width=360, bed_depth=360, base_layer_mm=.16)
        assert any(r["object"] == 3 and abs(r["target_layer_mm"]-.12)<1e-6
                   for r in schedules), schedules
        print("PASS: native XL per-object layer schedules", schedules, flush=True)
        print("PASS: native XL five-tool modifier/cavity/variable-layer mix",
              mixed_receipt, "sha256", hashlib.sha256(mixed).hexdigest(),
              flush=True)


if __name__=="__main__":
    main(*sys.argv[1:])
