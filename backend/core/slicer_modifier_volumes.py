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
        optional_fields = {"assembly_id", "kind"}
        if not isinstance(entry, dict):
            raise ValueError("Invalid native modifier record.")
        fields = set(entry)
        if not base_fields.issubset(fields) or (fields - base_fields - optional_fields) not in (set(), pose_fields):
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
        kind = entry.get("kind", "modifier")
        if kind not in ("modifier", "negative"):
            raise ValueError("Unknown non-printing volume type.")
        assembly = entry.get("assembly_id")
        if assembly is not None and (not isinstance(assembly, str) or
                                    not assembly.startswith("assembly:") or len(assembly) > 100):
            raise ValueError("Invalid volume assembly identity.")
        settings = validate_process_overrides(entry["settings"])
        if kind == "modifier" and (not settings or set(settings) - INITIAL_OVERRIDE_KEYS):
            raise ValueError("Modifier requires verified candidate wall or infill settings.")
        if kind == "negative" and settings:
            raise ValueError("Negative volumes cannot contain process overrides.")
        result.append({"id": uid, "shape": entry["shape"], **values, **pose,
                       "kind": kind, "assembly_id": assembly, "settings": settings})
    return result



# Explicit exact-version scope for the first owner-verified, single-material
# production modifier route. A new binary must re-prove regional G-code effects.
VERIFIED_NATIVE_MODIFIER_VERSIONS = {
    "orcaslicer": "2.5.0",
    "crealityprint": "7.3.1",
    "bambustudio": "02.09.01.70",
}

# Exact pinned real-binary two-model acceptance passed for all three
# engines on PR #196. Each acceptance sliced identical baseline, infill
# modifier and negative-cutter 3MF fixtures, and asserted regional G-code
# extrusion changed in the intended directions on BOTH printable objects.
# Orca: native-modifier-orca.yml; Creality: native-modifier-creality.yml;
# Bambu: bambu-real-binary.yml (placement-aware native output sampling).
# Keep this allowlist exact-version only: no blanket engine/version approval.
VERIFIED_NATIVE_COMPOSITE_VERSIONS = {
    "orcaslicer": "2.5.0",
    "crealityprint": "7.3.1",
    "bambustudio": "02.09.01.70",
}
VERIFIED_NATIVE_NEGATIVE_VERSIONS = {
    "orcaslicer": "2.5.0",
    "crealityprint": "7.3.1",
    "bambustudio": "02.09.01.70",
}
MAX_NATIVE_COMPOSITE_MODELS = 12


def assert_native_plate_volume_coverage(plate, settings):
    """Never silently slice only the first twelve of a free-volume draft.

    Plate-level storage supports up to 48 independent non-printing volumes;
    the temporary editor/slicer adapter still supports only twelve per mesh.
    Drafts may retain unattached regions, but slicing must prove exact,
    complete adapter coverage before calling any engine.
    """
    if not isinstance(settings, dict) or "plate_volumes" not in settings:
        return
    raw = settings["plate_volumes"]
    if not isinstance(raw, list) or len(raw) > MAX_TOTAL_MODIFIERS:
        raise ValueError("Independent plate volume list is invalid.")
    canonical = []
    for offset in range(0, len(raw), MAX_MODIFIERS_PER_MODEL):
        canonical.extend(validate_modifier_volumes(
            raw[offset:offset + MAX_MODIFIERS_PER_MODEL]))
    if (any(volume.get("coordinate_space") != "world" for volume in canonical)
            or len({v["id"] for v in canonical}) != len(canonical)):
        raise ValueError("Independent plate volume identities or coordinates are invalid.")
    if not isinstance(plate, list):
        raise ValueError("An independent volume plate requires a printable model for slicing.")
    inline = [
        volume for model in plate if isinstance(model, dict)
        for volume in validate_modifier_volumes(model.get("modifier_volumes"))
        if volume.get("coordinate_space") == "world"
    ]
    if sorted(inline, key=lambda row: row["id"]) != sorted(
            canonical, key=lambda row: row["id"]):
        raise ValueError(
            "Some independently saved modifier or negative volumes cannot be represented "
            "in the native slicer input. Save the draft; do not slice with missing regions."
        )


def validate_native_modifier_execution(plate, *, engine, version, settings):
    """Strict exact-version native region admission. No unverified combinations."""
    if not isinstance(plate, list):
        return False
    if any(not isinstance(row, dict) for row in plate):
        raise ValueError("Native modifier plate entries must be objects.")
    assert_native_plate_volume_coverage(plate, settings)
    count = sum(len(row.get("modifier_volumes") or []) for row in plate)
    if not count:
        return False
    if not 1 <= len(plate) <= MAX_NATIVE_COMPOSITE_MODELS or count > MAX_TOTAL_MODIFIERS:
        raise ValueError("Native region slicing exceeds the bounded model or volume limit.")
    if VERIFIED_NATIVE_MODIFIER_VERSIONS.get(engine) != version:
        raise ValueError("Native modifier engine/version has not passed pinned real-binary acceptance.")
    if len(plate) > 1 and VERIFIED_NATIVE_COMPOSITE_VERSIONS.get(engine) != version:
        raise ValueError("Composite native modifier slicing requires real-binary multi-model acceptance for this engine/version.")
    if not isinstance(settings, dict):
        raise ValueError("Invalid native modifier slicing request settings.")
    if (settings.get("multi_material_test") or settings.get("flush_settings")
            or settings.get("material_tool_bindings")
            or settings.get("slot_filament_profiles") or settings.get("prime_tower")):
        raise ValueError("Combining regions with native multi-material routing is unverified.")
    seen = set()
    negative = False
    for model in plate:
        fields = ("colour_paint", "support_paint", "seam_paint",
                  "fuzzy_skin_paint", "negative_volumes", "variable_layer_profile")
        if any(model.get(field) for field in fields):
            raise ValueError("Native regions with other geometry extensions require separate verification.")
        volumes = validate_modifier_volumes(model.get("modifier_volumes"))
        if len(volumes) > MAX_MODIFIERS_PER_MODEL:
            raise ValueError("Too many native region volumes on one model.")
        if len(plate) > 1 and model.get("process_overrides"):
            raise ValueError("Composite native regional and per-model process settings are not verified together.")
        for volume in volumes:
            if volume["id"] in seen:
                raise ValueError("Native volume identities must be unique across the plate.")
            seen.add(volume["id"])
            if volume["kind"] == "negative":
                negative = True
                if volume.get("coordinate_space") != "world":
                    raise ValueError("Negative volumes require independent plate-space coordinates.")
            if len(plate) > 1 and volume.get("coordinate_space") != "world":
                raise ValueError("Composite regions require independent world-space coordinates.")
    if len(seen) != count:
        raise ValueError("Invalid native region count.")
    if negative and VERIFIED_NATIVE_NEGATIVE_VERSIONS.get(engine) != version:
        raise ValueError("Native negative-volume slicing requires pinned real-binary subtraction evidence for this engine/version.")
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
