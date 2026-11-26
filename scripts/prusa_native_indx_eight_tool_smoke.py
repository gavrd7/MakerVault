"""Native pinned Prusa 2.9.7 eight-tool independent-head qualification.

Offline test only. Extends the reviewed official XL 5T print profile's
nozzle count in an ephemeral INDX-style candidate. No artificial dock/pickup
or printer start commands are created; hardware transfer is not demonstrated.
All eight tool IDs must deposit inside their own spatial model footprint.
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
    flatten_prusa_vendor_preset, validate_flat_prusa_preset)
from slicer_worker.service import _decode_payload
from slicer_worker.runner import run_prusa
from slicer_worker.prusa_material_gcode_audit import audit_prusa_material_model_gcode


def _settings(raw):
    return validate_flat_prusa_preset(raw, kind="printer")


def candidate_printer(source):
    # Official XL 5T defaults to binary G-code; text-only MakerVault worker
    # requires its resolved temporary profile to select ASCII *before* parse.
    source = b"\n".join(
        b"binary_gcode = 0" if line.split(b"=",1)[0].strip()==b"binary_gcode"
        else line for line in source.splitlines()) + b"\n"
    settings = _settings(source)
    if len(settings["nozzle_diameter"].split(",")) != 5:
        raise ValueError("INDX research expects native 5T baseline profile.")
    settings["nozzle_diameter"] = ",".join(["0.4"] * 8)
    settings["binary_gcode"] = "0"
    settings["single_extruder_multi_material"] = "0"
    # The base is an upstream native independent-head profile. All profile
    # fields are inherited; no physical pickup/docking G-code is fabricated.
    return "".join(f"{k} = {v}\n" for k, v in sorted(settings.items())).encode()


def main(binary, vendor):
    bundle = Path(vendor).read_bytes()
    digest = hashlib.sha256(bundle).hexdigest()
    xl = flatten_prusa_vendor_preset(
        bundle, kind="printer", name="Original Prusa XL - 5T 0.4 nozzle",
        expected_sha256=digest)
    printer = candidate_printer(xl)
    basic = flatten_prusa_vendor_preset(
        bundle, kind="filament", name="Generic PLA",
        expected_sha256=digest)
    filament_options = validate_flat_prusa_preset(basic,kind="filament")
    profiles = []
    for index in range(8):
        settings = dict(filament_options)
        settings["temperature"] = str(200 + index * 5)
        settings["first_layer_temperature"] = str(205 + index * 5)
        profiles.append("".join(
            f"{k} = {v}\n" for k, v in sorted(settings.items())).encode())
    palette = compile_prusa_filament_palette(printer,profiles)
    process = flatten_prusa_vendor_preset(
        bundle,kind="print",name="0.20mm NORMAL",expected_sha256=digest)
    options = validate_flat_prusa_preset(process,kind="print")
    for key in ("wipe_tower","wipe_into_infill","wipe_into_objects"):
        options[key] = "0"
    process = "".join(
        f"{k} = {v}\n" for k,v in sorted(options.items())).encode()
    positions = (-115,-82,-49,-16,17,50,83,116)
    rows = []
    for index,x in enumerate(positions):
        obj=item(x_mm=x)
        obj["asset_id"]="indx-eight-"+str(index)
        rows.append((obj,cube(size=8)))
    tools=list(range(1,9))
    project,topology=build_prusa_multitool_candidate(
        rows,printer_ini=printer,tools=tools,bed_width=360,bed_depth=360)
    assert topology["kind"]=="indx" and topology["logical_tool_count"]==8
    encode=lambda data:base64.b64encode(data).decode()
    payload = {
        "job_id":str(uuid.uuid4()),"engine":"prusaslicer",
        "engine_version":"2.9.7","model_format":"3mf",
        "model":encode(project),"printer_profile":encode(printer),
        "filament_profile":encode(palette),"process_profile":encode(process),
        "prusa_offline_xl":{"tools":tools}}
    receipt=_decode_payload(payload)
    assert receipt["prusa_offline_xl"]["tools"]==tools
    with tempfile.TemporaryDirectory(prefix="prusa-indx-eight-") as root:
        folder=Path(root)
        for name,raw in (
            ("input.3mf",project),("printer.ini",printer),
            ("filament.ini",palette),("process.ini",process)):
            (folder/name).write_bytes(raw)
        (folder/"prusa-offline-xl.marker").write_text("v1")
        run_prusa(Path(binary),folder)
        gcode=(folder/"output.gcode").read_bytes()
        observed=audit_prusa_material_model_gcode(
            gcode,project,printer_ini=printer,tools=tools)
        if (len(observed["correct_extrusion_moves"])!=8
                or min(observed["correct_extrusion_moves"])<20
                or observed["incorrect_extrusion_moves"]!=[0]*8
                or observed["selected_tools"]!=tuple(range(8))):
            raise AssertionError("Native eight-tool deposition did not match all eight models.")
        print("PASS: pinned Prusa 2.9.7 independently deposited T0-T7 on eight models",
              observed,"sha256",hashlib.sha256(gcode).hexdigest(),flush=True)


if __name__=="__main__":
    main(*sys.argv[1:])
