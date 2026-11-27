"""Create deterministic isolated native 3MF qualification fixtures, no printer IO."""
import sys
from pathlib import Path
from core.slicer_prusa_3mf import build_prusa_native_3mf
from scripts.prusa_real_binary_smoke import cube_stl

def main(folder):
    out = Path(folder)
    out.mkdir(parents=True, exist_ok=True)
    base = {"asset_id": "verified-cube", "y_mm": 0, "z_mm": 0,
            "rotation_deg": 0, "scale_percent": 100}
    for name, kind, settings in (
        ("baseline", None, {}),
        ("modifier", "modifier", {"sparse_infill_density": 80}),
        ("negative", "negative", {}),
    ):
        models = []
        for x in (-35, 35):
            item = {**base, "x_mm": x}
            if kind:
                item["modifier_volumes"] = [{
                    "id": ("523af5de-f6dd-41c0-b130-cc50b471cde2"
                           if x < 0 else "44e9d68a-775c-4ff9-82d5-a0e51042cc49"),
                    "shape": "box", "kind": kind,
                    "width_mm": 10, "depth_mm": 10, "height_mm": 22,
                    "x_mm": x, "y_mm": 0, "z_mm": 10,
                    "coordinate_space": "world",
                    "rotation_xyz_deg": [0, 0, 0],
                    "scale_xyz_percent": [100, 100, 100],
                    "settings": settings,
                }]
            models.append((item, cube_stl()))
        (out / (name + ".3mf")).write_bytes(build_prusa_native_3mf(
            models, bed_width=250, bed_depth=210))


    # Mixed feature parity: an independently placed parameter modifier on
    # the first model and a native Object infill override on the second.
    # Single-feature controls let the runtime prove neither feature leaks
    # across object boundaries.
    first_x, second_x = -35, 35
    modifier = {
        "id": "d973b9bb-f114-4e92-b8d9-aa0c988c6626",
        "shape": "box", "kind": "modifier",
        "width_mm": 10, "depth_mm": 10, "height_mm": 22,
        "x_mm": first_x, "y_mm": 0, "z_mm": 10,
        "coordinate_space": "world",
        "rotation_xyz_deg": [0, 0, 0],
        "scale_xyz_percent": [100, 100, 100],
        "settings": {"sparse_infill_density": 80},
    }
    for label, with_modifier, with_object, with_negative in (
        ("mix-baseline", False, False, False),
        ("mix-modifier", True, False, False),
        ("mix-object", False, True, False),
        ("mix-both", True, True, False),
        ("mix-negative-object", False, True, True),
    ):
        left = {**base, "x_mm": first_x}
        right = {**base, "x_mm": second_x}
        if with_modifier:
            left["modifier_volumes"] = [modifier]
        if with_negative:
            left["modifier_volumes"] = [{**modifier, "kind": "negative",
                                        "settings": {}}]
        if with_object:
            right["process_overrides"] = {"sparse_infill_density": 80}
        archive = build_prusa_native_3mf(
            [(left, cube_stl()), (right, cube_stl())],
            bed_width=250, bed_depth=210)
        (out / (label + ".3mf")).write_bytes(archive)

if __name__ == "__main__":
    main(sys.argv[1])
