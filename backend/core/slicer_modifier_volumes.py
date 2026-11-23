"""Strict, engine-neutral draft contract for native parameter-modifier volumes.

A modifier never becomes an independently printable plate model. Its geometry
must remain a child of one owned parent in the native project. Native slicing
is denied until each engine's real-binary regional-effect fixture is approved.
"""
import math
import uuid

from .slicer_process_settings import validate_process_overrides

PRIMITIVE_SHAPES = frozenset({"box", "cylinder", "sphere", "cone", "disc", "torus"})
MAX_MODIFIERS_PER_MODEL = 12
MAX_TOTAL_MODIFIERS = 48
# Strict first native slice candidates; not a promise of cross-engine parity.
INITIAL_OVERRIDE_KEYS = frozenset({"wall_loops", "sparse_infill_density"})
_NUMERIC = ("width_mm", "depth_mm", "height_mm", "x_mm", "y_mm", "z_mm")


def validate_modifier_volumes(raw):
    """Sanitise a model's owned modifier geometry; no custom mesh or G-code."""
    if raw is None:
        return []
    if not isinstance(raw, list) or len(raw) > MAX_MODIFIERS_PER_MODEL:
        raise ValueError("Modifier list exceeds the per-model limit.")
    seen = set()
    result = []
    for entry in raw:
        if not isinstance(entry, dict) or set(entry) != {
            "id", "shape", *_NUMERIC, "settings"
        }:
            raise ValueError("Invalid native modifier fields.")
        try:
            uid = str(uuid.UUID(str(entry["id"])))
        except (ValueError, AttributeError, TypeError):
            raise ValueError("Modifier identity must be a UUID.") from None
        if uid in seen:
            raise ValueError("Duplicate modifier identity on one model.")
        seen.add(uid)
        if not isinstance(entry["shape"], str) or entry["shape"] not in PRIMITIVE_SHAPES:
            raise ValueError("Unsupported primitive modifier shape.")
        values = {}
        for key in _NUMERIC:
            value = entry[key]
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
                raise ValueError("Modifier dimensions and position must be finite.")
            if key in {"width_mm", "depth_mm", "height_mm"}:
                if not 0.5 <= value <= 500:
                    raise ValueError("Modifier dimensions must be 0.5 to 500 mm.")
            elif not -10000 <= value <= 10000:
                raise ValueError("Modifier position is out of bounds.")
            values[key] = round(float(value), 3)
        settings = validate_process_overrides(entry["settings"])
        if not settings or set(settings) - INITIAL_OVERRIDE_KEYS:
            raise ValueError("Modifier requires verified candidate wall or infill settings.")
        result.append({"id": uid, "shape": entry["shape"], **values, "settings": settings})
    return result


def refuse_unverified_native_modifiers(plate, engine):
    """Never silently slice modifiers as normal printable primitives or drop them."""
    if not isinstance(plate, list):
        return
    count = sum(len(row.get("modifier_volumes") or [])
                for row in plate if isinstance(row, dict))
    if count > MAX_TOTAL_MODIFIERS:
        raise ValueError("Too many native modifiers on the build plate.")
    if count:
        raise ValueError(
            "Native parameter modifier slicing has not passed verified regional "
            f"G-code tests for {engine}. Save the draft; do not slice with ignored modifiers."
        )
