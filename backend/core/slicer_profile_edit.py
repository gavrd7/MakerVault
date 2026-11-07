"""Bounded edits for independent OrcaSlicer/Creality Print native JSON profiles.

Creates a candidate *copy*, never mutates a verified or official preset.
Limited common controls are deliberately not a claim of full native GUI parity.
"""
import json
import math

from .slicer_profiles import SlicerProfileError, _check_orca_json


# Numeric limits are intentionally conservative; the native engine still decides
# whether the final combination is valid for a particular printer/material.
SETTINGS = {
    "printer": {
        "nozzle_diameter": (0.1, 2.0),
        "retract_length": (0, 20),
    },
    "filament": {
        "nozzle_temperature": (100, 350),
        "hot_plate_temp": (0, 150),
        "cool_plate_temp": (0, 150),
        "textured_plate_temp": (0, 150),
        "filament_flow_ratio": (0.5, 1.5),
    },
    "process": {
        "layer_height": (0.05, 1.0),
        "initial_layer_print_height": (0.05, 1.0),
        "sparse_infill_density": (0, 100),
        "wall_loops": (1, 12),
        "outer_wall_speed": (5, 500),
    },
}


def customise_native_json(raw: bytes, kind: str, name: str, edits: dict) -> bytes:
    if kind not in SETTINGS:
        raise SlicerProfileError("Invalid native profile category.")
    if not isinstance(name, str) or not 1 <= len(name.strip()) <= 200:
        raise SlicerProfileError("A custom profile name is required.")
    if not isinstance(edits, dict) or not edits or len(edits) > 12:
        raise SlicerProfileError("Choose at least one supported setting.")
    if set(edits) - set(SETTINGS[kind]):
        raise SlicerProfileError("A native setting is not supported by the GUI editor.")
    if not isinstance(raw, bytes) or not raw or len(raw) > 1024 * 1024:
        raise SlicerProfileError("Original native profile is missing or too large.")
    try:
        data = json.loads(raw.decode("utf-8-sig"))
    except (ValueError, UnicodeDecodeError):
        raise SlicerProfileError("Native profile must be UTF-8 JSON.") from None
    if not isinstance(data, dict):
        raise SlicerProfileError("Native profile must be a JSON object.")
    _check_orca_json(json.dumps(data))
    for key, value in edits.items():
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
            raise SlicerProfileError("Native numeric settings must be finite.")
        minimum, maximum = SETTINGS[kind][key]
        if not minimum <= value <= maximum:
            raise SlicerProfileError("Native setting is outside the supported range.")
        if key in {"wall_loops"} and not float(value).is_integer():
            raise SlicerProfileError("Wall count must be an integer.")
        formatted = str(int(value)) if float(value).is_integer() else str(round(value, 4))
        if key not in data:
            raise SlicerProfileError("This native profile does not define the selected setting.")
        existing = data[key]
        if key == "sparse_infill_density":
            formatted += "%"
        # Both slicers have native JSON presets containing scalar and array values.
        # Retain the type shape where known; the engine-specific verifier must
        # still validate the complete resolved profile before use.
        if isinstance(existing, list):
            data[key] = [formatted for _ in existing] if existing else [formatted]
        else:
            data[key] = formatted
    data["name"] = name.strip()
    result = json.dumps(data, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    if len(result) > 1024 * 1024:
        raise SlicerProfileError("Custom profile exceeds the size limit.")
    _check_orca_json(result.decode("utf-8"))
    return result
