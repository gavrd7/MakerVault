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
import io
import zipfile
from defusedxml import ElementTree as SafeET

from core.slicer_prusa_multitool_project import build_prusa_multitool_candidate
from core.slicer_prusa_filament_palette import compile_prusa_filament_palette
from core.tests.test_slicer_prusa_plate import cube, item
from core.tests.test_slicer_prusa_3mf import volume
from slicer_worker.prusa_material_validation import validate_prusa_material_candidate
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


def main(binary, vendor, official=None):
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

        # Validate modifier/infill and negative-volume combinations through
        # the actual eight-tool worker, not just 3MF metadata acceptance.
        modifier=volume("modifier",{"sparse_infill_density":80})
        modifier.update(width_mm=3,depth_mm=3,height_mm=5,
                        x_mm=positions[0],y_mm=0,z_mm=4)
        cavity=volume("negative",{})
        cavity.update(width_mm=3,depth_mm=3,height_mm=5,
                      x_mm=positions[1],y_mm=0,z_mm=4)
        extended=[]
        for index,(obj,mesh) in enumerate(rows):
            updated=dict(obj)
            if index==0:
                updated["modifier_volumes"]=[modifier]
            if index==1:
                updated["modifier_volumes"]=[cavity]
            if index==2:
                updated["variable_layer_profile"]={
                    "version":1,"bands":[
                        {"from_mm":2,"to_mm":6,"layer_mm":.12}]}
            extended.append((updated,mesh))
        extended_project,_=build_prusa_multitool_candidate(
            extended,printer_ini=printer,tools=tools,bed_width=360,bed_depth=360)
        from slicer_worker.prusa_material_validation import _qualified_topology
        with zipfile.ZipFile(io.BytesIO(extended_project)) as archive:
            config=SafeET.fromstring(archive.read("Metadata/Slic3r_PE_model.config"))
        assert sum(len(obj.findall("volume"))-1 for obj in config.findall("object"))==2
        assert "Metadata/Prusa_Slicer_layer_config_ranges.xml" in zipfile.ZipFile(io.BytesIO(extended_project)).namelist()
        assert _qualified_topology(printer)==(8,False)
        assert validate_prusa_material_candidate(
            extended_project,printer_ini=printer,tools=tools)["objects"]==8
        payload["model"]=encode(extended_project)
        _decode_payload(payload)
        (folder/"input.3mf").write_bytes(extended_project)
        (folder/"output.gcode").unlink()
        run_prusa(Path(binary),folder)
        changed=(folder/"output.gcode").read_bytes()
        changed_audit=audit_prusa_material_model_gcode(
            changed,extended_project,printer_ini=printer,tools=tools)
        assert changed_audit["selected_tools"]==tuple(range(8))
        assert changed_audit["incorrect_extrusion_moves"]==[0]*8
        assert min(changed_audit["correct_extrusion_moves"])>=20
        assert hashlib.sha256(changed).digest()!=hashlib.sha256(gcode).digest()
        print("PASS: eight-tool INDX typed native modifier and negative",
              changed_audit,"sha256",hashlib.sha256(changed).hexdigest(),flush=True)

        if official is not None:
            # A second real-binary slice must accept the actual Prusa-
            # distributed INDX machine profile and its exact toolchange
            # settings, not only the expanded XL independent-head control.
            source=Path(official).read_bytes()
            from slicer_worker.prusa_vendor_profiles import KEY
            outliers=[]
            for raw_line in source.decode("utf-8-sig").splitlines():
                line=raw_line.strip()
                if not line or line.startswith(("#",";","[")) or "=" not in line:
                    continue
                key,_,value=line.partition("=")
                key,value=key.strip(),value.strip()
                if not KEY.fullmatch(key) or len(value)>65536:
                    outliers.append((key[:64],len(value),bool(KEY.fullmatch(key))))
            print("Official INDX vendor extended literals",outliers[:12],
                  "total",len(outliers),flush=True)
            selected=flatten_prusa_vendor_preset(
                source,kind="printer",
                name="Prusa CORE One INDX 8T HF0.4 nozzle",
                expected_sha256=hashlib.sha256(source).hexdigest())
            selected=b"\n".join(
                b"binary_gcode = 0"
                if line.split(b"=",1)[0].strip()==b"binary_gcode"
                else line for line in selected.splitlines())+b"\n"
            settings=validate_flat_prusa_preset(selected,kind="printer")
            if (len(settings["nozzle_diameter"].split(","))!=8 or
                    settings.get("single_extruder_multi_material","0") not in
                    ("0","false")):
                raise AssertionError("Official INDX eight-tool profile has incompatible topology.")
            actual_positions=(-100,-72,-44,-16,12,40,68,96)
            actual_rows=[]
            for index,x in enumerate(actual_positions):
                native=item(x_mm=x)
                native["asset_id"]="official-indx-"+str(index)
                actual_rows.append((native,cube(size=8)))
            official_project,_=build_prusa_multitool_candidate(
                actual_rows,printer_ini=selected,tools=tools,
                bed_width=250,bed_depth=210)
            payload["printer_profile"]=encode(selected)
            payload["model"]=encode(official_project)
            _decode_payload(payload)
            (folder/"input.3mf").write_bytes(official_project)
            (folder/"printer.ini").write_bytes(selected)
            (folder/"output.gcode").unlink()
            run_prusa(Path(binary),folder)
            observed_official=audit_prusa_material_model_gcode(
                (folder/"output.gcode").read_bytes(),official_project,
                printer_ini=selected,tools=tools)
            if (observed_official["selected_tools"]!=tuple(range(8)) or
                    observed_official["incorrect_extrusion_moves"]!=[0]*8 or
                    min(observed_official["correct_extrusion_moves"])<20):
                raise AssertionError("Actual official INDX 8T native material attribution failed.")
            print("PASS: actual official Prusa CORE One INDX 8T profile "
                  "slices all eight tool identities",observed_official,flush=True)




if __name__=="__main__":
    main(*sys.argv[1:])
