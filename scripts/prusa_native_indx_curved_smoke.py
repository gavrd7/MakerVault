"""Genuine pinned Prusa 2.9.7 INDX 8T curved T1 surface paint research.

The eight-head topology is an ephemeral, fully self-contained profile built
from the reviewed official XL5 printer preset, matching MakerVault's
existing independent INDX acceptance. No pickup scripts are invented.
A successful print is NOT claimed: only signed offline native G-code.
"""
import hashlib
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

from core.slicer_prusa_colour_project import build_prusa_colour_candidate
from core.slicer_prusa_filament_palette import compile_prusa_filament_palette
from core.slicer_prusa_process_settings import apply_prusa_process_overrides
from scripts.prusa_native_curved_colour_research import (
    cylinder_stl,mask_for,deposited_sectors)
from scripts.prusa_native_indx_eight_tool_smoke import candidate_printer
from slicer_worker.prusa_curved_surface import (
    inspect_prusa_curved_surface,audit_prusa_curved_surface_gcode)
from slicer_worker.prusa_vendor_profiles import (
    flatten_prusa_vendor_preset,validate_flat_prusa_preset)
from slicer_worker.prusa_gcode_audit import audit_prusa_positive_e
from slicer_worker.runner import run_prusa


def main(binary,vendor):
    blob=Path(vendor).read_bytes()
    digest=hashlib.sha256(blob).hexdigest()
    def preset(kind,name):
        return flatten_prusa_vendor_preset(
            blob,kind=kind,name=name,expected_sha256=digest)
    printer=candidate_printer(
        preset("printer","Original Prusa XL - 5T 0.4 nozzle"))
    material=validate_flat_prusa_preset(
        preset("filament","Generic PLA"),kind="filament")
    profiles=[]
    for temp in (205,210,215,220,225,230,235,240):
        profile={**material,"temperature":str(temp),
                 "first_layer_temperature":str(temp)}
        profiles.append("".join(
            f"{k} = {v}\n"
            for k,v in sorted(profile.items())).encode())
    filament=compile_prusa_filament_palette(printer,profiles)
    raw=validate_flat_prusa_preset(
        preset("print","0.20mm NORMAL"),kind="print")
    for key in ("wipe_tower","wipe_into_infill","wipe_into_objects"):
        raw[key]="0"
    process=apply_prusa_process_overrides(
        "".join(f"{key} = {value}\n"
                for key,value in sorted(raw.items())).encode(),
        {"layer_height":.16,"wall_loops":3})
    mesh=cylinder_stl()
    paint=mask_for(mesh)
    project=build_prusa_colour_candidate(
        {"asset_id":"indx8-curved-brush","x_mm":0,"y_mm":0,
         "z_mm":0,"rotation_deg":0,"scale_percent":100,
         "colour_paint":paint},
        mesh,printer_ini=printer,colour_tool_indices={1:1},
        bed_width=360,bed_depth=360)
    signed=inspect_prusa_curved_surface(project,1)
    assert signed["painted_facets"]>20 and signed["unpainted_facets"]>100
    with TemporaryDirectory(prefix="prusa-indx-curved-") as directory:
        work=Path(directory)
        for name,data in (("input.3mf",project),("printer.ini",printer),
                          ("filament.ini",filament),("process.ini",process)):
            (work/name).write_bytes(data)
        (work/"prusa-offline-xl-colour.marker").write_text("v1")
        run_prusa(Path(binary),work,timeout_seconds=300)
        gcode=(work/"output.gcode").read_bytes()
        audit_prusa_positive_e(gcode)
        angular=deposited_sectors(gcode)
        proof=audit_prusa_curved_surface_gcode(
            gcode,project,tool=1)
        assert not proof["wipe_tower"]
        print("PASS: native independent INDX 8T signed T1 curved "
              "source-surface G-code",angular,proof,
              hashlib.sha256(gcode).hexdigest(),flush=True)


if __name__=="__main__":
    main(*sys.argv[1:])
