"""Prusa-only numeric process overrides qualified against native 2.9.7 CLI.

Canonical workbench keys map to native Prusa INI keys. Never mutate a stored
preset, introduce arbitrary keys, or accept executable/string payloads.
"""
import math
from .slicer_prusa_native_resolution import parse_prusa_profile
from .slicer_process_settings import PROCESS_FIELDS, BASIC_FIELDS, SECTION_FOR

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
    settings = parse_prusa_profile(raw, "process")
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
    parse_prusa_profile(output, "process")
    return output

def prusa_process_schema(raw):
    settings = parse_prusa_profile(raw, "process")
    result = {}
    for key, (native, lo, hi, integer, suffix) in FIELDS.items():
        value = settings.get(native, "")
        if suffix and not value.endswith(suffix):
            continue
        try:
            current = float(value.removesuffix(suffix) if suffix else value)
        except ValueError:
            continue
        if not math.isfinite(current) or not lo <= current <= hi or (integer and not current.is_integer()):
            continue
        category, label, unit, *_ = PROCESS_FIELDS[key]
        result[key] = {"category": category, "label": label, "unit": unit,
                       "minimum": lo, "maximum": hi, "integer": integer,
                       "current": current, "level": "basic" if key in BASIC_FIELDS else "advanced",
                       "section": SECTION_FOR.get(key, "Advanced")}
    return result


def enable_prusa_painted_support(raw):
    """Enable upstream support generation only for a painted enforcer request.

    Keep the user's explicit automatic/manual support choice when present.
    The original private profile stays immutable. No arbitrary process keys,
    executable hooks or material mappings are accepted from the browser.
    """
    options = parse_prusa_profile(raw, "process")
    options["support_material"] = "1"
    # A sparse user preset without this key defaults to manual-only supports;
    # never silently enable automatic supports in response to painted enforcers.
    options.setdefault("support_material_auto", "0")
    output = "".join(f"{key} = {value}\n" for key, value in sorted(options.items())).encode("utf-8")
    parse_prusa_profile(output, "process")
    return output
