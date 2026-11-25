"""Read-only Prusa 2.9.7 pinned vendor MMU/XL profile inventory.

Does not install printer profiles, enable multi-material or create G-code.
The actual upstream inheritance chain determines valid native extruder types.
"""
from pathlib import Path
import re
import sys
import hashlib

from slicer_worker.prusa_vendor_profiles import (
    parse_prusa_vendor_bundle, flatten_prusa_vendor_preset,
    validate_flat_prusa_preset,
)

def main(path):
    raw = Path(path).read_bytes()
    sha = hashlib.sha256(raw).hexdigest()
    sections = parse_prusa_vendor_bundle(raw)
    selected = [key for key in sections
                if key.startswith("printer:") and
                any(term in key.lower() for term in ("mmu3", "mmu2s", "xl 5t", "xl 2t", "xl 5", "xl 2"))]
    print("Pinned Prusa native MMU/XL printer source candidates:", len(selected))
    for section in selected[:45]:
        name = section[len("printer:"):]
        try:
            parsed = validate_flat_prusa_preset(flatten_prusa_vendor_preset(
                raw, kind="printer", name=name, expected_sha256=sha), kind="printer")
        except ValueError as exc:
            print("UNRESOLVED", name, type(exc).__name__, str(exc))
            continue
        print("CANDIDATE", repr(name), {
            key:parsed.get(key) for key in (
                "printer_technology", "nozzle_diameter", "single_extruder_multi_material",
                "extruder_colour", "wipe_tower", "min_layer_height", "max_layer_height",
                "bed_shape", "gcode_flavor", "toolchange_gcode",
            ) if key in parsed and key != "toolchange_gcode"
        })
    if not selected:
        raise ValueError("Official pinned Prusa 2.9.7 source has no MMU/XL candidates.")
    print("PASS: read-only native multi-material/independent-toolhead source inventory.")

if __name__ == "__main__":
    main(sys.argv[1])
