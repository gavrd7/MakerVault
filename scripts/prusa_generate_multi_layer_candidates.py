"""Construct independent-object Prusa 2.9.7 native layer range fixtures."""
from pathlib import Path
import sys

from core.slicer_prusa_3mf import build_prusa_native_3mf
from scripts.prusa_real_binary_smoke import cube_stl


def main(destination):
    root = Path(destination)
    root.mkdir(parents=True, exist_ok=True)
    source = cube_stl()
    base = {"asset_id": "qualified-cube", "y_mm": 0, "z_mm": 0,
            "rotation_deg": 0, "scale_percent": 100}
    layers = {"version": 1, "bands": [
        {"from_mm": 4, "to_mm": 16, "layer_mm": .12}]}
    for label, change in (("baseline", False), ("left-variable", True)):
        left = {**base, "x_mm": -35}
        right = {**base, "x_mm": 35}
        if change:
            left["variable_layer_profile"] = layers
        raw = build_prusa_native_3mf([
            (left, source), (right, source)], bed_width=250, bed_depth=210)
        (root/(label + ".3mf")).write_bytes(raw)

if __name__ == "__main__":
    main(sys.argv[1])
