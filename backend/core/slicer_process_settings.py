"""Bounded, process-only OrcaSlicer settings for the interactive workbench.

These are *native process keys*, not a synthetic MakerVault slicer format.
Overrides are applied only to an ephemeral resolved native process profile.
No printer/filament/start/filament-change G-code or post-processing fields
are editable through this interface. An absent key is never fabricated.
"""
import json
import math

from .slicer_profiles import SlicerProfileError, _check_orca_json

# key: (category, user-visible label, unit, minimum, maximum, integer_only)
PROCESS_FIELDS = {
    "layer_height": ("Quality", "Layer height", "mm", 0.05, 1.0, False),
    "initial_layer_print_height": ("Quality", "First layer height", "mm", 0.05, 1.0, False),
    "line_width": ("Quality", "Default line width", "mm", 0.1, 2.0, False),
    "outer_wall_line_width": ("Quality", "Outer wall line width", "mm", 0.1, 2.0, False),
    "wall_loops": ("Strength", "Wall loops", "", 1, 12, True),
    "top_shell_layers": ("Strength", "Top shell layers", "", 0, 20, True),
    "bottom_shell_layers": ("Strength", "Bottom shell layers", "", 0, 20, True),
    "sparse_infill_density": ("Strength", "Sparse infill density", "%", 0, 100, False),
    "outer_wall_speed": ("Speed", "Outer wall speed", "mm/s", 5, 500, False),
    "inner_wall_speed": ("Speed", "Inner wall speed", "mm/s", 5, 500, False),
    "sparse_infill_speed": ("Speed", "Sparse infill speed", "mm/s", 5, 500, False),
    "travel_speed": ("Speed", "Travel speed", "mm/s", 10, 1000, False),
    "support_threshold_angle": ("Supports", "Support threshold angle", "°", 0, 90, False),
    "support_interface_top_layers": ("Supports", "Top interface layers", "", 0, 10, True),
    "brim_width": ("Others", "Brim width", "mm", 0, 50, False),
    "skirt_loops": ("Others", "Skirt loops", "", 0, 20, True),
}


def _scalar(value):
    if isinstance(value, list):
        if not value or len(value) > 8 or any(item != value[0] for item in value):
            return None
        value = value[0]
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        return None
    try:
        result = float(str(value).strip().removesuffix("%"))
    except ValueError:
        return None
    return result if math.isfinite(result) else None


def process_schema(raw):
    """Describe present, recognised keys in an integrity-checked process preset."""
    try:
        profile = _check_orca_json(raw.decode("utf-8-sig"))
    except (UnicodeDecodeError, ValueError):
        raise SlicerProfileError("Cannot inspect the selected native process profile.") from None
    result = {}
    for key, (category, label, unit, lo, hi, integer) in PROCESS_FIELDS.items():
        if key not in profile:
            continue
        current = _scalar(profile[key])
        if current is None or not lo <= current <= hi:
            continue
        result[key] = {
            "category": category, "label": label, "unit": unit,
            "minimum": lo, "maximum": hi, "integer": integer,
            "current": current,
        }
    return result


def validate_process_overrides(overrides):
    if overrides in (None, {}):
        return {}
    if not isinstance(overrides, dict) or len(overrides) > len(PROCESS_FIELDS):
        raise ValueError("Invalid native process overrides.")
    validated = {}
    for key, value in overrides.items():
        if key not in PROCESS_FIELDS or isinstance(value, bool) or not isinstance(value, (float, int)):
            raise ValueError("Unsupported native process setting.")
        if not math.isfinite(value):
            raise ValueError("Native process settings must be finite.")
        _, _, _, lo, hi, integer = PROCESS_FIELDS[key]
        if not lo <= value <= hi or (integer and not float(value).is_integer()):
            raise ValueError("Native process setting is outside its permitted range.")
        validated[key] = int(value) if integer else round(float(value), 4)
    return validated


def apply_process_overrides(raw, overrides):
    validated = validate_process_overrides(overrides)
    if not validated:
        return raw
    try:
        profile = _check_orca_json(raw.decode("utf-8-sig"))
    except (UnicodeDecodeError, ValueError):
        raise ValueError("Native process profile could not be read.") from None
    available = process_schema(raw)
    if set(validated) - set(available):
        raise ValueError("A selected native process setting is unavailable in this profile.")
    for key, number in validated.items():
        previous = profile[key]
        formatted = str(number) + ("%" if key == "sparse_infill_density" else "")
        profile[key] = [formatted for _ in previous] if isinstance(previous, list) else formatted
    output = json.dumps(profile, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    if len(output) > 1024 * 1024:
        raise ValueError("Updated native process profile exceeds its size limit.")
    _check_orca_json(output.decode("utf-8"))
    return output
