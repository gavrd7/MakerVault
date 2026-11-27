"""Genuine Prusa 2.9.7 XL five-head facet-paint feasibility experiment.

Research only. Does not use or relax MakerVault's independently audited
production worker admission; exact XL native G-code is inspected offline.
"""
import hashlib
from pathlib import Path
import sys
from tempfile import TemporaryDirectory

from core.slicer_prusa_colour_project import build_prusa_colour_candidate
from core.slicer_prusa_filament_palette import compile_prusa_filament_palette
from scripts.prusa_generate_mmu_paint import fixture
from scripts.prusa_native_five_colour_paint_smoke import painted_external_walls
from slicer_worker.prusa_vendor_profiles import (
    flatten_prusa_vendor_preset, validate_flat_prusa_preset)
from slicer_worker.runner import run_prusa


def main(binary, vendor):
    blob=Path(vendor).read_bytes()
    source_sha=hashlib.sha256(blob).hexdigest()
    resolve=lambda kind,name:flatten_prusa_vendor_preset(
        blob,kind=kind,name=name,expected_sha256=source_sha)
    printer=resolve("printer","Original Prusa XL - 5T 0.4 nozzle")
    printer=b"\n".join(
        b"binary_gcode = 0" if line.split(b"=",1)[0].strip()==b"binary_gcode"
        else line for line in printer.splitlines())+b"\n"
    machine=validate_flat_prusa_preset(printer,kind="printer")
    assert machine.get("single_extruder_multi_material","0") in ("0","false")
    assert len(machine["nozzle_diameter"].split(","))==5
    stock=validate_flat_prusa_preset(resolve("filament","Generic PLA"),kind="filament")
    filaments=[]
    for temp in (205,210,215,220,225):
        row={**stock,"temperature":str(temp),"first_layer_temperature":str(temp)}
        filaments.append("".join(f"{key} = {value}\n"
                        for key,value in sorted(row.items())).encode())
    palette=compile_prusa_filament_palette(printer,filaments)
    base=validate_flat_prusa_preset(resolve("print","0.20mm NORMAL"),kind="print")
    for key in ("wipe_tower","wipe_into_infill","wipe_into_objects"):
        base[key]="0"
    process="".join(f"{key} = {value}\n"
                    for key,value in sorted(base.items())).encode()
    stl,_,_,paint=fixture(include_paint=True)
    row={"asset_id":"xl-native-paint-research","x_mm":0,"y_mm":0,"z_mm":0,
         "rotation_deg":0,"scale_percent":100,"colour_paint":paint}
    project=build_prusa_colour_candidate(
        row,stl,printer_ini=printer,colour_tool_indices={1:1},
        bed_width=360,bed_depth=360)
    with TemporaryDirectory(prefix="prusa-xl-paint-research-") as folder:
        work=Path(folder)
        for name,data in (
            ("input.3mf",project),("printer.ini",printer),
            ("filament.ini",palette),("process.ini",process)):
            (work/name).write_bytes(data)
        # Exercise the same dedicated XL marker as the authenticated worker.
        # The service independently admits and audits the 3MF before writing it.
        (work/"prusa-offline-xl-colour.marker").write_text("v1")
        run_prusa(Path(binary),work)
        output=(work/"output.gcode").read_bytes()
        counts=painted_external_walls(output,center_x=180,center_y=180)
        assert counts[1]["front"]>=20,counts
        assert counts[0]["back"]>=20,counts
        assert counts[1]["back"]<=2,counts
        assert counts[0]["front"]<=2,counts
        for key in (2,3,4):
            assert counts[key]["front"]<=2 and counts[key]["back"]<=2,counts
        from slicer_worker.prusa_colour_gcode_audit import audit_prusa_xl_colour_gcode
        receipt=audit_prusa_xl_colour_gcode(
            output,project,printer_ini=printer,tool=1)
        assert receipt["painted_wall_moves"][1]["front"]>20
        assert receipt["painted_wall_moves"][0]["back"]>20
        assert receipt["wipe_tower"] is False
        print("PASS: genuine independent XL5 T1-front/T0-back paint",
              counts,receipt,"sha256",hashlib.sha256(output).hexdigest(),
              flush=True)


if __name__=="__main__":
    main(*sys.argv[1:])
