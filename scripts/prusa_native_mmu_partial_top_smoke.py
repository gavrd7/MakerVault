"""Genuine pinned Prusa 2.9.7 MMU partial top-face paint research.

Intentionally offline and never usable as printer-start authorisation. A
negative result is informative: the production whole-wall gate stays intact.
"""
import hashlib
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

from core.slicer_plate_3mf import _triangles
from core.slicer_prusa_colour_project import build_prusa_colour_candidate
from core.slicer_prusa_filament_palette import compile_prusa_filament_palette
from core.slicer_prusa_process_settings import apply_prusa_process_overrides
from core.slicer_prusa_purge import compile_prusa_purge_matrix
from core.slicer_prusa_wipe_tower import add_prusa_native_wipe_tower
from core.slicer_native_support_paint import _fingerprint
from scripts.prusa_generate_mmu_paint import fixture
from slicer_worker.prusa_top_surface import (
    inspect_prusa_partial_top, audit_prusa_partial_top_gcode)
from slicer_worker.prusa_gcode_audit import run_prusa_mmu_with_numeric_recheck
from slicer_worker.prusa_vendor_profiles import (
    flatten_prusa_vendor_preset, validate_flat_prusa_preset)
from slicer_worker.runner import run_prusa


def main(binary, vendor_path):
    vendor = Path(vendor_path).read_bytes()
    checksum = hashlib.sha256(vendor).hexdigest()
    def preset(kind, name):
        return flatten_prusa_vendor_preset(
            vendor, kind=kind, name=name, expected_sha256=checksum)
    printer = preset("printer", "Original Prusa i3 MK3S & MK3S+ MMU3")
    filament = validate_flat_prusa_preset(
        preset("filament", "Generic PLA"), kind="filament")
    palette = []
    for temp in (205, 210, 215, 220, 225):
        settings = dict(filament)
        settings["temperature"] = str(temp)
        settings["first_layer_temperature"] = str(temp)
        palette.append("".join(
            f"{key} = {value}\n" for key, value in sorted(settings.items())
        ).encode())
    native_filaments = compile_prusa_filament_palette(printer, palette)
    process = apply_prusa_process_overrides(
        preset("print", "0.20mm NORMAL"),
        {"layer_height": .16, "wall_loops": 3})
    process = compile_prusa_purge_matrix(
        printer, process, [
            [0 if i == j else 80 for j in range(5)]
            for i in range(5)])
    stl, _, _, paint = fixture(include_paint=True)
    triangles = list(_triangles(stl))
    low = [min(p[a] for face in triangles for p in face)
           for a in range(3)]
    high = [max(p[a] for face in triangles for p in face)
            for a in range(3)]
    origin = ((low[0] + high[0]) / 2,
              (low[1] + high[1]) / 2, low[2])
    local = [
        [tuple(p[a] - origin[a] for a in range(3))
         for p in face] for face in triangles]
    face_index = next(i for i, face in enumerate(local)
                      if all(abs(p[2]-(high[2]-low[2])) < 1e-5
                             for p in face))
    a, b, c = local[face_index]
    # Genuine polygon inside one original face, not a whole-face switch.
    ab = [(a[i] + b[i]) / 2 for i in range(3)]
    ac = [(a[i] + c[i]) / 2 for i in range(3)]
    partial = {**paint, "signature": _fingerprint(local),
               "regions": [{
                   "slot": 1,
                   "patches": [{"face": face_index,
                                "polygon": [list(a), ab, ac]}],
               }]}
    row = {"asset_id": "mmu-top-native-colour",
           "x_mm": 0, "y_mm": 0, "z_mm": 0,
           "rotation_deg": 0, "scale_percent": 100,
           "colour_paint": partial}
    project = build_prusa_colour_candidate(
        row, stl, printer_ini=printer, colour_tool_indices={1: 1},
        bed_width=250, bed_depth=210)
    project = add_prusa_native_wipe_tower(
        project, x_mm=55, y_mm=150, rotation_deg=0,
        bed_width=250, bed_depth=210)
    mask = inspect_prusa_partial_top(project, 1)
    print("MMU top-surface source geometry",
          {"painted_area_mm2": mask["painted_area_mm2"],
           "unpainted_area_mm2": mask["unpainted_area_mm2"]},
          flush=True)
    with TemporaryDirectory(prefix="prusa-mmu-top-colour-") as folder:
        work = Path(folder)
        for name, data in (
                ("input.3mf", project), ("printer.ini", printer),
                ("filament.ini", native_filaments),
                ("process.ini", process)):
            (work / name).write_bytes(data)
        (work / "prusa-offline-colour.marker").write_text("v1")
        _, gcode = run_prusa_mmu_with_numeric_recheck(
            run_prusa, Path(binary), work, timeout_seconds=300,
            max_bytes=64 * 1024 * 1024)
        proof = audit_prusa_partial_top_gcode(
            gcode, project, tool=1, tower=(55, 150, 0, 250, 210))
        print("PASS: genuine Prusa MMU partial top painted colour with tower",
              proof, "sha256", hashlib.sha256(gcode).hexdigest(),
              flush=True)


if __name__ == "__main__":
    main(*sys.argv[1:])
