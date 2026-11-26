"""Five independent XL toolhead toolpaths: genuine pinned Prusa 2.9.7 research.

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
        raw,kind="printer",name="Original Prusa XL - 5T 0.4 nozzle",
        expected_sha256=digest)
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
    encode=lambda data:base64.b64encode(data).decode()
    candidate={
        "job_id":str(uuid.uuid4()),"engine":"prusaslicer",
        "engine_version":"2.9.7","model_format":"3mf",
        "model":encode(project),"printer_profile":encode(printer),
        "filament_profile":encode(palette),"process_profile":encode(process),
        "prusa_offline_xl":{"tools":tools}}
    checked=_decode_payload(candidate)
    assert checked["prusa_offline_xl"]["tools"]==tools
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
            print("PASS: five XL independent heads selected and deposited correct material on five models",
              receipt,"sha256",hashlib.sha256(output).hexdigest(),flush=True)


if __name__=="__main__":
    main(*sys.argv[1:])
