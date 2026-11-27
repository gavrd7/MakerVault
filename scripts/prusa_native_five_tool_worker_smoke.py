"""Five independent MMU toolpaths: genuine pinned Prusa 2.9.7 research.

This only validates offline G-code, not hardware/printer submission.
"""
import base64
import hashlib
from pathlib import Path
import sys
import tempfile
import uuid
import math

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
from slicer_worker.prusa_gcode_audit import run_prusa_mmu_with_numeric_recheck


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
        "outer_wall_speed":24, "inner_wall_speed":42,
        "sparse_infill_speed":60, "travel_speed":145,
        "top_surface_speed":29,
    })
    assert b"layer_height = 0.16\n" in process
    assert b"perimeters = 3\n" in process
    assert b"fill_density = 23%\n" in process
    for native_key, expected in (
        (b"external_perimeter_speed", b"24"), (b"perimeter_speed", b"42"),
        (b"infill_speed", b"60"), (b"travel_speed", b"145"),
        (b"top_solid_infill_speed", b"29"),
    ):
        assert native_key + b" = " + expected + b"\n" in process


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
        _receipt,output=run_prusa_mmu_with_numeric_recheck(
            run_prusa,Path(binary),work,timeout_seconds=300,
            max_bytes=64*1024*1024)
        # Native fixture diagnostics only. Never emit user G-code in the
        # production worker, but identify an out-of-range generator value.
        from slicer_worker.prusa_gcode_audit import WORD
        impossible=[]
        for lineno,raw_line in enumerate(output.splitlines(),1):
            cmd=raw_line.decode("utf-8","replace").split(";",1)[0].strip()
            if not cmd or cmd.split(None,1)[0].upper() not in (
                    "G0","G00","G1","G01","G92"):
                continue
            for key,value in WORD.findall(cmd):
                try:
                    number=float(value)
                except ValueError:
                    continue
                if not math.isfinite(number) or abs(number)>1e9:
                    impossible.append((lineno,key,format(number,".6g"),
                                       cmd[:100]))
                    if len(impossible)>=8:
                        break
            if len(impossible)>=8:
                break
        if impossible:
            print("Research: generator numeric outliers",impossible,flush=True)
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

        # More objects than MMU bays: each of the five real logical tools
        # must independently deposit inside three distinct object footprints.
        # Never extrapolate the machine's actual five native material tools.
        repeated_rows=[]
        for row_index, y_mm in enumerate((-73, -43, 17)):
            for index, x_mm in enumerate((-90, -45, 0, 45, 90)):
                obj=item(x_mm=x_mm,y_mm=y_mm)
                obj["asset_id"]=f"mmu-repeat-{row_index}-{index}"
                repeated_rows.append((obj,cube(size=8)))
        repeated_tools=list(range(1,6))*3
        repeated_project,_=build_prusa_multitool_candidate(
            repeated_rows,printer_ini=printer,tools=repeated_tools,
            bed_width=250,bed_depth=210)
        repeated_project=add_prusa_native_wipe_tower(
            repeated_project,x_mm=55,y_mm=150,rotation_deg=0,
            bed_width=250,bed_depth=210)
        from slicer_worker.prusa_material_validation import validate_prusa_material_candidate
        validated=validate_prusa_material_candidate(
            repeated_project,printer_ini=printer,tools=repeated_tools,tower=tower)
        assert validated["objects"]==15
        repeated_payload={**candidate,"model":encode(repeated_project),
                          "prusa_offline_mmu":{"tools":repeated_tools,"tower":tower}}
        assert _decode_payload(repeated_payload)["prusa_offline_mmu"]["tools"]==repeated_tools
        (work/"input.3mf").write_bytes(repeated_project)
        (work/"output.gcode").unlink()
        _receipt,repeated_gcode=run_prusa_mmu_with_numeric_recheck(
            run_prusa,Path(binary),work,timeout_seconds=300,
            max_bytes=64*1024*1024)
        repeated_receipt=audit_prusa_material_model_gcode(
            repeated_gcode,repeated_project,printer_ini=printer,
            tools=repeated_tools,tower=tower)
        assert len(repeated_receipt["correct_extrusion_moves"])==15
        assert min(repeated_receipt["correct_extrusion_moves"])>=20
        assert repeated_receipt["incorrect_extrusion_moves"]==[0]*15
        assert len(repeated_receipt["tower_extrusion_moves"])==5
        print("PASS: fifteen Prusa MMU models repeat five native tools with audited deposition",
              repeated_receipt,"sha256",hashlib.sha256(repeated_gcode).hexdigest(),flush=True)

        # Diagnose the shared native mapping independently for modifiers,
        # variable-layer ranges and their composition. A missing native
        # output is a genuine compatibility failure, not a feature lock.
        from core.tests.test_slicer_prusa_3mf import volume
        from core.slicer_prusa_spatial_layers import audit_prusa_multi_object_layer_ranges
        from slicer_worker.runner import WorkerError
        from slicer_worker.prusa_material_validation import validate_prusa_material_candidate
        failures=[]
        # Pinned 2.9.7 produces no output for MMU per-object variable-Z
        # ranges. This is an observed engine incompatibility; verify the
        # working native modifier mapping rather than admitting bad jobs.
        for label,with_modifier,with_layers in (
            ("modifier",True,False),
        ):
            region_rows=[]
            for index,(model,source) in enumerate(rows):
                mapped=dict(model)
                if index==0 and with_modifier:
                    shape=volume("modifier", {"sparse_infill_density":80})
                    shape.update(x_mm=-90,y_mm=0,z_mm=4,
                                 width_mm=3,depth_mm=3,height_mm=5)
                    mapped["modifier_volumes"]=[shape]
                if index==1 and with_layers:
                    mapped["variable_layer_profile"]={"version":1,"bands":[
                        {"from_mm":2,"to_mm":6,"layer_mm":.12}]}
                region_rows.append((mapped,source))
            try:
                candidate,_=build_prusa_multitool_candidate(
                    region_rows,printer_ini=printer,tools=tools,
                    bed_width=250,bed_depth=210)
                candidate=add_prusa_native_wipe_tower(
                    candidate,x_mm=55,y_mm=150,rotation_deg=0,
                    bed_width=250,bed_depth=210)
                native_receipt=validate_prusa_material_candidate(
                    candidate,printer_ini=printer,tools=tools,tower=tower)
                assert native_receipt["objects"]==5
                (work/"input.3mf").write_bytes(candidate)
                (work/"output.gcode").unlink(missing_ok=True)
                _receipt,generated=run_prusa_mmu_with_numeric_recheck(
                    run_prusa,Path(binary),work,timeout_seconds=300,
                    max_bytes=64*1024*1024)
                material=audit_prusa_material_model_gcode(
                    generated,candidate,printer_ini=printer,
                    tools=tools,tower=tower)
                assert material["incorrect_extrusion_moves"]==[0]*5
                layers=None
                if with_layers:
                    layers=audit_prusa_multi_object_layer_ranges(
                        generated,region_rows,bed_width=250,bed_depth=210,
                        base_layer_mm=.16)
                    assert any(row["object"]==2 and
                               row["target_layer_mm"]==.12
                               for row in layers),layers
                print("PASS: native Prusa MMU mapping",label,material,layers,
                      flush=True)
            except (WorkerError,ValueError,AssertionError) as exc:
                failures.append((label,type(exc).__name__,str(exc)))
                print("NATIVE MMU MAPPING BLOCKER",failures[-1],flush=True)
        # Research the exact upstream adhesion mapping rather than assume
        # that a generic material assignment proof also qualifies brim and
        # skirt. A rejected native G-code is reported, not accepted or
        # sanitised; this diagnostic never enables physical submission.
        adhesion_settings={"brim_width":3,"skirt_loops":2}
        adhesion=apply_prusa_process_overrides(process,adhesion_settings)
        (work/"input.3mf").write_bytes(project)
        (work/"process.ini").write_bytes(adhesion)
        (work/"output.gcode").unlink(missing_ok=True)
        try:
            _adhesion_receipt,adhesion_gcode=run_prusa_mmu_with_numeric_recheck(
                run_prusa,Path(binary),work,timeout_seconds=300,
                max_bytes=64*1024*1024)
            from collections import Counter
            role_counts=Counter()
            for line in adhesion_gcode.splitlines():
                if line.startswith(b";TYPE:"):
                    role_counts[line[6:].strip().decode("ascii","replace")]+=1
            try:
                evidence=audit_prusa_material_model_gcode(
                    adhesion_gcode,project,printer_ini=printer,
                    tools=tools,tower=tower)
                print("NATIVE PRUSA ADHESION RESEARCH: model tool attribution accepted",
                      evidence,"roles",dict(role_counts),flush=True)
            except WorkerError as exc:
                print("NATIVE PRUSA ADHESION RESEARCH: separate spatial audit needed",
                      type(exc).__name__,str(exc),"roles",dict(role_counts),
                      flush=True)
        except WorkerError as exc:
            print("NATIVE PRUSA ADHESION RESEARCH: CLI rejected requested settings",
                  type(exc).__name__,str(exc),flush=True)
        finally:
            (work/"process.ini").write_bytes(process)

        if failures:
            raise AssertionError(
                "Some Prusa MMU native mapping combinations need compatibility fixes: "
                +repr(failures))

if __name__=="__main__":
    main(*sys.argv[1:])
