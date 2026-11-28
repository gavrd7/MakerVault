"""Research-only genuine Prusa XL independent-head worker acceptance.

Actual physical pickup, offsets and printer submission remain unqualified.
"""
import base64
import hashlib
from pathlib import Path
import tempfile
import sys
import uuid

from core.slicer_prusa_filament_palette import compile_prusa_filament_palette
from slicer_worker.prusa_vendor_profiles import (
    flatten_prusa_vendor_preset,validate_flat_prusa_preset)
from slicer_worker.service import _decode_payload
from slicer_worker.runner import WorkerError,run_prusa
from slicer_worker.prusa_material_gcode_audit import audit_prusa_material_model_gcode


def main(binary,vendor,projects):
    raw=Path(vendor).read_bytes()
    digest=hashlib.sha256(raw).hexdigest()
    printer=flatten_prusa_vendor_preset(
        raw,kind="printer",name="Original Prusa XL - 2T 0.4 nozzle",
        expected_sha256=digest)
    printer=b"\n".join(
        b"binary_gcode = 0" if line.split(b"=",1)[0].strip()==b"binary_gcode" else line
        for line in printer.splitlines())+b"\n"
    filament=flatten_prusa_vendor_preset(
        raw,kind="filament",name="Generic PLA",expected_sha256=digest)
    process=flatten_prusa_vendor_preset(
        raw,kind="print",name="0.20mm NORMAL",expected_sha256=digest)
    machine=validate_flat_prusa_preset(printer,kind="printer")
    assert machine.get("single_extruder_multi_material","0") in ("0","false")
    assert len(machine["nozzle_diameter"].split(","))==2
    settings=validate_flat_prusa_preset(filament,kind="filament")
    filaments=[]
    for temperature in (205,220):
        row=dict(settings)
        row["temperature"]=str(temperature)
        row["first_layer_temperature"]=str(temperature)
        filaments.append("".join(
            f"{key} = {value}\n" for key,value in sorted(row.items())).encode())
    palette=compile_prusa_filament_palette(printer,filaments)
    process_options=validate_flat_prusa_preset(process,kind="print")
    for key in ("wipe_tower","wipe_into_infill","wipe_into_objects"):
        process_options[key]="0"
    process="".join(f"{key} = {value}\n"
                    for key,value in sorted(process_options.items())).encode()
    project=(Path(projects)/"object.3mf").read_bytes()
    enc=lambda data:base64.b64encode(data).decode()
    payload={
        "job_id":str(uuid.uuid4()),"engine":"prusaslicer",
        "engine_version":"2.9.7","model_format":"3mf",
        "model":enc(project),"printer_profile":enc(printer),
        "filament_profile":enc(palette),"process_profile":enc(process),
        "prusa_offline_xl":{"tools":[1,2]},
    }
    decoded=_decode_payload(payload)
    assert decoded["prusa_offline_xl"]["tools"]==[1,2]
    for change in (
        {"prusa_offline_xl":{"tools":[1,1]}},
        {"prusa_offline_mmu":{"tools":[1,2],"tower":[55,150,0,250,210]}}):
        try:
            _decode_payload({**payload,**change})
        except WorkerError:
            pass
        else:
            raise AssertionError("Unqualified XL payload accepted.")
    with tempfile.TemporaryDirectory(prefix="prusa-xl-offline-") as temp:
        root=Path(temp)
        for name,data in (("input.3mf",project),("printer.ini",printer),
                          ("filament.ini",palette),("process.ini",process)):
            (root/name).write_bytes(data)
        (root/"prusa-offline-xl.marker").write_text("v1")
        run_prusa(Path(binary),root)
        output=(root/"output.gcode").read_bytes()
        audit=audit_prusa_material_model_gcode(
            output,project,printer_ini=printer,tools=[1,2])
        assert audit["incorrect_extrusion_moves"]==[0,0]
        assert min(audit["correct_extrusion_moves"])>100
        print("PASS: real Prusa 2.9.7 independent XL two-tool offline native worker execution",
              audit,"G-code sha256",hashlib.sha256(output).hexdigest(),flush=True)


if __name__=="__main__":
    main(*sys.argv[1:])
