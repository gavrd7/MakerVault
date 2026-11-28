"""Research genuine rotated, slanted partial XL5 colour; no dispatch."""
import hashlib
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

from core.slicer_plate_3mf import _triangles
from core.slicer_native_support_paint import _fingerprint
from core.slicer_prusa_colour_project import build_prusa_colour_candidate
from core.slicer_prusa_filament_palette import compile_prusa_filament_palette
from core.slicer_prusa_process_settings import apply_prusa_process_overrides
from scripts.prusa_generate_mmu_paint import fixture
from slicer_worker.prusa_slanted_surface import (
    inspect_prusa_slanted_surface, audit_prusa_slanted_surface_gcode)
from slicer_worker.prusa_vendor_profiles import (
    flatten_prusa_vendor_preset, validate_flat_prusa_preset)
from slicer_worker.prusa_material_validation import validate_prusa_material_candidate
from slicer_worker.runner import run_prusa


def main(binary, vendor):
    raw = Path(vendor).read_bytes()
    sha = hashlib.sha256(raw).hexdigest()
    def get(kind, name):
        return flatten_prusa_vendor_preset(
            raw, kind=kind, name=name, expected_sha256=sha)
    printer = get("printer", "Original Prusa XL - 5T 0.4 nozzle")
    printer = b"\n".join(
        b"binary_gcode = 0" if line.split(b"=", 1)[0].strip() == b"binary_gcode"
        else line for line in printer.splitlines()) + b"\n"
    base_filament = validate_flat_prusa_preset(
        get("filament", "Generic PLA"), kind="filament")
    filament_profiles = []
    for temp in (205, 210, 215, 220, 225):
        settings = {**base_filament,
                    "temperature": str(temp),
                    "first_layer_temperature": str(temp)}
        filament_profiles.append("".join(
            f"{k} = {v}\n" for k, v in sorted(settings.items())).encode())
    filament = compile_prusa_filament_palette(printer, filament_profiles)
    settings = validate_flat_prusa_preset(
        get("print", "0.20mm NORMAL"), kind="print")
    for key in ("wipe_tower", "wipe_into_infill", "wipe_into_objects"):
        settings[key] = "0"
    process = apply_prusa_process_overrides(
        "".join(f"{k} = {v}\n" for k, v in sorted(settings.items())).encode(),
        {"layer_height": .16, "wall_loops": 3})
    stl, _, _, colour = fixture(include_paint=True)
    faces = list(_triangles(stl))
    low = [min(p[i] for face in faces for p in face) for i in range(3)]
    high = [max(p[i] for face in faces for p in face) for i in range(3)]
    origin = ((low[0]+high[0])/2, (low[1]+high[1])/2, low[2])
    local = [[tuple(p[i]-origin[i] for i in range(3)) for p in face]
             for face in faces]
    target = colour["regions"][0]["patches"][0]["face"]
    a, b, c = local[target]
    colour = {
        **colour, "signature": _fingerprint(local),
        "regions": [{"slot": 1, "patches": [{
            "face": target, "polygon": [
                list(a), [(a[i]+b[i])/2 for i in range(3)],
                [(a[i]+c[i])/2 for i in range(3)]]}]}]}
    project = build_prusa_colour_candidate(
        {"asset_id": "xl-slanted-brush", "x_mm": 0, "y_mm": 0,
         "z_mm": 0, "rotation_deg": 0, "rotation_xyz_deg": [30, 0],
         "scale_percent": 100,
         "colour_paint": colour},
        stl, printer_ini=printer, colour_tool_indices={1: 1},
        bed_width=360, bed_depth=360)
    receipt = validate_prusa_material_candidate(
        project, printer_ini=printer, colour=True, independent_colour=True)
    assert receipt["tools"] == (1, 2)
    with TemporaryDirectory(prefix="prusa-xl-slanted-brush-") as dirname:
        folder = Path(dirname)
        for name, value in (
                ("input.3mf", project), ("printer.ini", printer),
                ("filament.ini", filament), ("process.ini", process)):
            (folder / name).write_bytes(value)
        (folder / "prusa-offline-xl-colour.marker").write_text("v1")
        run_prusa(Path(binary), folder)
        output = (folder / "output.gcode").read_bytes()
        proof = audit_prusa_partial_wall_gcode(
            output, project, tool=1)
        print("PASS: genuine XL5 slanted surface partial T1 deposition",
              proof, hashlib.sha256(output).hexdigest(), flush=True)


if __name__ == "__main__":
    main(*sys.argv[1:])
