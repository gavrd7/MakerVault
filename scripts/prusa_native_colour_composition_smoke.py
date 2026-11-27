"""Genuine Prusa 2.9.7 painted XL/MMU editing composition research.

The normal slice-worker intentionally rejects these as unqualified. Prove
native deposition for each requested effect without printer dispatch.
"""
import hashlib
import sys
import uuid
from pathlib import Path
from tempfile import TemporaryDirectory

from core.slicer_prusa_colour_project import build_prusa_colour_candidate
from core.slicer_prusa_filament_palette import compile_prusa_filament_palette
from core.slicer_prusa_purge import compile_prusa_purge_matrix
from core.slicer_prusa_process_settings import apply_prusa_process_overrides
from core.slicer_prusa_wipe_tower import add_prusa_native_wipe_tower
from scripts.prusa_generate_mmu_paint import fixture
from scripts.prusa_native_regions_smoke import regional_extrusion
from scripts.prusa_native_five_colour_paint_smoke import painted_external_walls
from slicer_worker.prusa_vendor_profiles import (
    flatten_prusa_vendor_preset, validate_flat_prusa_preset)
from slicer_worker.prusa_gcode_audit import (
    run_prusa_mmu_with_numeric_recheck, audit_prusa_positive_e)
from slicer_worker.runner import run_prusa


def primitive(kind, x):
    return {
        "id": str(uuid.uuid4()), "kind": kind, "shape": "box",
        "width_mm": 6, "depth_mm": 10, "height_mm": 18,
        "x_mm": x, "y_mm": 0, "z_mm": 10,
        "coordinate_space": "world",
        "rotation_xyz_deg": [0, 0, 0],
        "scale_xyz_percent": [100, 100, 100],
        "settings": {"sparse_infill_density": 85} if kind == "modifier" else {},
    }


def main(binary, vendor):
    raw = Path(vendor).read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    def preset(kind, name):
        return flatten_prusa_vendor_preset(
            raw, kind=kind, name=name, expected_sha256=digest)
    printer = preset("printer", "Original Prusa i3 MK3S & MK3S+ MMU3")
    material = validate_flat_prusa_preset(
        preset("filament", "Generic PLA"), kind="filament")
    filaments = []
    for temp in (205, 210, 215, 220, 225):
        selected = {**material, "temperature": str(temp),
                    "first_layer_temperature": str(temp)}
        filaments.append("".join(
            f"{key} = {value}\\n" for key, value in sorted(selected.items())
        ).encode())
    palette = compile_prusa_filament_palette(printer, filaments)
    process = apply_prusa_process_overrides(
        preset("print", "0.20mm NORMAL"), {
            "layer_height": .16, "wall_loops": 3})
    process = compile_prusa_purge_matrix(
        printer, process, [[0 if i == j else 80 for j in range(5)]
                           for i in range(5)])
    stl, _, _, paint = fixture(include_paint=True)
    original = {"asset_id": "native-composition-test",
                "x_mm": 0, "y_mm": 0, "z_mm": 0,
                "rotation_deg": 0, "scale_percent": 100,
                "colour_paint": paint,
                "process_overrides": {"wall_loops": 4}}
    left = primitive("modifier", -6)
    right = primitive("negative", 6)
    experiments = (
        ("baseline", []),
        ("modifier", [left]),
        ("negative", [right]),
        ("combined", [left, right]),
    )
    output = {}
    with TemporaryDirectory(prefix="prusa-compound-colour-") as dirname:
        for label, volumes in experiments:
            row = {**original, "modifier_volumes": volumes}
            project = build_prusa_colour_candidate(
                row, stl, printer_ini=printer,
                colour_tool_indices={1: 1}, bed_width=250, bed_depth=210,
                research_compound=bool(volumes))
            project = add_prusa_native_wipe_tower(
                project, x_mm=55, y_mm=150, rotation_deg=0,
                bed_width=250, bed_depth=210)
            folder = Path(dirname) / label
            folder.mkdir()
            for filename, payload in (
                    ("input.3mf", project),
                    ("printer.ini", printer),
                    ("filament.ini", palette),
                    ("process.ini", process)):
                (folder / filename).write_bytes(payload)
            (folder / "prusa-offline-colour.marker").write_text("v1")
            _, data = run_prusa_mmu_with_numeric_recheck(
                run_prusa, Path(binary), folder, timeout_seconds=300,
                max_bytes=64 * 1024 * 1024)
            positive = audit_prusa_positive_e(data)
            assert positive["positive_e_moves"] > 100
            walls = painted_external_walls(data)
            assert walls[1]["front"] >= 20, (label, walls)
            assert walls[1]["back"] <= 2, (label, walls)
            measured = {
                "modifier": regional_extrusion(
                    data, center_x=119, center_y=105),
                "cavity": regional_extrusion(
                    data, center_x=131, center_y=105),
            }
            output[label] = measured
            print("Prusa genuine compound colour", label,
                  "wall", walls[1], "regions", measured,
                  "sha256", hashlib.sha256(data).hexdigest(), flush=True)
    baseline = output["baseline"]
    combined = output["combined"]
    # A combination only qualifies when both independent local changes remain
    # observable in the *same* sliced output, not simply a valid 3MF/archive.
    if not (baseline["modifier"][0] > .05 and
            baseline["cavity"][0] > .05 and
            output["modifier"]["modifier"][0] >
                baseline["modifier"][0] * 1.2 and
            output["negative"]["cavity"][0] <
                baseline["cavity"][0] * .5 and
            combined["modifier"][0] >
                baseline["modifier"][0] * 1.2 and
            combined["cavity"][0] <
                baseline["cavity"][0] * .5):
        raise AssertionError(
            "Prusa painted native modifier/cavity composition did not retain "
            "both independently observed regional effects.")
    print("PASS: genuine native Prusa paint+Object+modifier+cavity "
          "multi-region toolpath deposition", flush=True)


if __name__ == "__main__":
    main(*sys.argv[1:])
