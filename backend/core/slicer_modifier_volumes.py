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
        base_fields = {"id", "shape", *_NUMERIC, "settings"}
        pose_fields = {"coordinate_space", "rotation_xyz_deg", "scale_xyz_percent"}
        fields = set(entry)
        if fields not in (base_fields, base_fields | pose_fields):
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
        pose = {}
        if fields & pose_fields:
            if entry["coordinate_space"] != "world":
                raise ValueError("New independent modifier poses must use plate coordinates.")
            for key, size, low, high in (
                ("rotation_xyz_deg", 3, -360, 360),
                ("scale_xyz_percent", 3, 5, 400),
            ):
                axes = entry[key]
                if (not isinstance(axes, list) or len(axes) != size or
                    any(isinstance(v, bool) or not isinstance(v, (int, float)) or
                        not math.isfinite(v) or not low <= v <= high for v in axes)):
                    raise ValueError("Invalid independent modifier rotation or scale.")
                pose[key] = [round(float(v), 3) for v in axes]
            pose["coordinate_space"] = "world"
        settings = validate_process_overrides(entry["settings"])
        if not settings or set(settings) - INITIAL_OVERRIDE_KEYS:
            raise ValueError("Modifier requires verified candidate wall or infill settings.")
        result.append({"id": uid, "shape": entry["shape"], **values, **pose, "settings": settings})
    return result



# Explicit exact-version scope for the first owner-verified, single-material
# production modifier route. A new binary must re-prove regional G-code effects.
VERIFIED_NATIVE_MODIFIER_VERSIONS = {
    "orcaslicer": "2.5.0",
    "crealityprint": "7.3.1",
    "bambustudio": "02.09.01.70",
}


def validate_native_modifier_execution(plate, *, engine, version, settings):
    """Accept only one safe native modifier owner; reject unproven combinations.

    This validates the request contract; archive, native profile and emitted
    G-code checks remain independently mandatory at worker execution.
    """
    if not isinstance(plate, list):
        return False
    count = sum(len(row.get("modifier_volumes") or [])
                for row in plate if isinstance(row, dict))
    if not count:
        return False
    if count > MAX_TOTAL_MODIFIERS or len(plate) != 1:
        raise ValueError("Native modifier slicing currently requires one model and at most twelve modifiers.")
    if VERIFIED_NATIVE_MODIFIER_VERSIONS.get(engine) != version:
        raise ValueError("Native modifier engine/version has not passed pinned real-binary acceptance.")
    if not isinstance(settings, dict):
        raise ValueError("Invalid modifier slicing request settings.")
    if (settings.get("multi_material_test") or settings.get("flush_settings")
            or settings.get("material_tool_bindings")
            or settings.get("slot_filament_profiles") or settings.get("prime_tower")):
        raise ValueError("Combining modifiers with native multi-material tool routing is not yet verified.")
    model = plate[0]
    if not isinstance(model, dict):
        raise ValueError("Invalid native modifier parent.")
    fields = ("colour_paint", "support_paint", "seam_paint",
              "fuzzy_skin_paint", "negative_volumes", "variable_layer_profile")
    if any(model.get(field) for field in fields):
        raise ValueError("Combining modifiers with other native geometry extensions requires separate verification.")
    validated = validate_modifier_volumes(model.get("modifier_volumes"))
    if len(validated) != count or count > MAX_MODIFIERS_PER_MODEL:
        raise ValueError("Invalid native modifier instance count.")
    return True



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
