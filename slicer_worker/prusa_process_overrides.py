"""Prusa-only numeric process overrides qualified against native 2.9.7 CLI.

Canonical workbench keys map to native Prusa INI keys. Never mutate a stored
preset, introduce arbitrary keys, or accept executable/string payloads.
"""
import math
from slicer_worker.prusa_vendor_profiles import validate_flat_prusa_preset

# canonical key: (native key, minimum, maximum, integer, suffix)
FIELDS = {
    "layer_height": ("layer_height", .05, .4, False, ""),
    "wall_loops": ("perimeters", 1, 12, True, ""),
    "top_shell_layers": ("top_solid_layers", 0, 20, True, ""),
    "bottom_shell_layers": ("bottom_solid_layers", 0, 20, True, ""),
    "sparse_infill_density": ("fill_density", 0, 100, False, "%"),
    "brim_width": ("brim_width", 0, 50, False, ""),
    "skirt_loops": ("skirts", 0, 20, True, ""),
}


def apply_prusa_process_overrides(raw, overrides):
    settings = validate_flat_prusa_preset(raw, kind="print")
    if not isinstance(overrides, dict) or set(overrides) - set(FIELDS):
        raise ValueError("Unsupported Prusa process override.")
    if not overrides:
        return raw
    for key, value in overrides.items():
        native, minimum, maximum, integer, suffix = FIELDS[key]
        if native not in settings:
            raise ValueError("Selected Prusa process setting is unavailable.")
        if (isinstance(value, bool) or not isinstance(value, (int, float))
                or not minimum <= value <= maximum or not math.isfinite(value)
                or (integer and not float(value).is_integer())):
            raise ValueError("Prusa process setting is outside its permitted range.")
        settings[native] = (str(int(value)) if integer else
                            format(value, ".4f").rstrip("0").rstrip(".")) + suffix
    output = "".join(f"{key} = {value}\n" for key, value in sorted(settings.items())).encode("utf-8")
    validate_flat_prusa_preset(output, kind="print")
    return output
