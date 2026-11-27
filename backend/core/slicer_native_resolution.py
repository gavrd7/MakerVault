"""Resolve imported engine-native JSON inheritance for isolated slice execution.

Resolution is strictly scoped to the same owner, engine, exact version and kind.
Do not alter stored originals or fall back to presets from another engine.
"""
import hashlib
import json

from .models import SlicerProfile
from .slicer_profiles import SlicerProfileError, _check_orca_json

MAX_RESOLVED_BYTES = 1024 * 1024
MAX_PARENT_DEPTH = 12


def resolved_native_profile(profile, *, depth=0, seen=None):
    if profile.engine == "prusaslicer":
        from .slicer_prusa_native_resolution import resolved_prusa_profile
        return resolved_prusa_profile(profile)
    if profile.engine == "bambustudio":
        from .slicer_bambu_native_resolution import resolved_bambu_profile
        return resolved_bambu_profile(profile)
    if profile.engine not in {"orcaslicer", "crealityprint"}:
        raise SlicerProfileError("Profile resolution currently supports Orca and Creality JSON.")
    seen = set() if seen is None else seen
    if depth >= MAX_PARENT_DEPTH or profile.pk in seen:
        raise SlicerProfileError("Native profile inheritance is circular or too deep.")
    if not profile.file_asset.file or profile.file_asset.owner_id != profile.owner_id:
        raise SlicerProfileError("Native profile source is not owned or available.")
    with profile.file_asset.file.storage.open(profile.file_asset.file.name, "rb") as source:
        raw = source.read(1024 * 1024 + 1)
    if len(raw) > 1024 * 1024 or hashlib.sha256(raw).hexdigest() != profile.content_sha256:
        raise SlicerProfileError("Native profile content changed since import.")
    try:
        obj = json.loads(raw.decode("utf-8-sig"))
    except (ValueError, UnicodeDecodeError):
        raise SlicerProfileError("Invalid native JSON profile.") from None
    if not isinstance(obj, dict):
        raise SlicerProfileError("Native profile must contain an object.")
    _check_orca_json(raw.decode("utf-8-sig"))
    parent_name = obj.get("inherits")
    if parent_name and (not isinstance(parent_name, str) or len(parent_name) > 200):
        raise SlicerProfileError("Native parent profile reference is invalid.")
    if parent_name:
        # Inheritance is resolved only inside the same exact upstream
        # catalogue scope. Never splice another vendor's same-named parent.
        parents = list(SlicerProfile.objects.select_related("file_asset").filter(
            owner_id=profile.owner_id, engine=profile.engine,
            engine_version=profile.engine_version, kind=profile.kind,
            name=parent_name, source_scope=profile.source_scope,
        )[:2])
        if not parents:
            raise SlicerProfileError("Native parent preset is missing in this source: " + parent_name)
        if len(parents) != 1:
            raise SlicerProfileError("Native parent preset identity is ambiguous.")
        parent = parents[0]
        base = resolved_native_profile(parent, depth=depth + 1, seen=seen | {profile.pk})
        merged = json.loads(base)
        # The child overrides parent fields; no merging across native kinds.
        merged.update(obj)
        obj = merged
    obj.pop("inherits", None)
    result = json.dumps(obj, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    if len(result) > MAX_RESOLVED_BYTES:
        raise SlicerProfileError("Resolved native preset is too large.")
    _check_orca_json(result.decode("utf-8"))
    return result


# Fixed allowlist: returned values are only boolean presence, depth and hashes.
# Never return user-provided preset names, machine scripts or file paths.
_CREALIY_PURGE_ORIGIN_KEYS = frozenset({
    "change_filament_gcode", "multicolor_method",
    "purge_in_prime_tower", "nozzle_volume",
    "single_extruder_multi_material", "flush_volumes_matrix",
    "flush_multiplier", "flush_volumes_changed",
})


def audit_creality_profile_origins(profile):
    """Read-only provenance of a *verified* Creality imported preset.

    Uses the same owner, exact version, native kind and source_scope rules as
    resolved_native_profile. Does not write the profiles or expose macro text.
    Each field is located at its nearest defining ancestor (child wins).
    """
    if profile.engine != "crealityprint":
        raise SlicerProfileError("Creality provenance audit requires a Creality preset.")
    current = profile
    seen = set()
    fields = {}
    depth = 0
    while current is not None:
        if depth >= MAX_PARENT_DEPTH or current.pk in seen:
            raise SlicerProfileError("Native profile inheritance is circular or too deep.")
        seen.add(current.pk)
        if not current.file_asset.file or current.file_asset.owner_id != current.owner_id:
            raise SlicerProfileError("Native profile source is not owned or available.")
        with current.file_asset.file.storage.open(current.file_asset.file.name, "rb") as source:
            raw = source.read(MAX_RESOLVED_BYTES + 1)
        if (not raw or len(raw) > MAX_RESOLVED_BYTES
                or hashlib.sha256(raw).hexdigest() != current.content_sha256):
            raise SlicerProfileError("Native profile content changed since import.")
        try:
            obj = json.loads(raw.decode("utf-8-sig"))
        except (ValueError, UnicodeDecodeError) as exc:
            raise SlicerProfileError("Invalid native JSON profile.") from exc
        if not isinstance(obj, dict):
            raise SlicerProfileError("Native profile must contain an object.")
        _check_orca_json(raw.decode("utf-8-sig"))
        for key in sorted(_CREALIY_PURGE_ORIGIN_KEYS):
            if key not in fields and key in obj:
                fields[key] = {
                    "defined": True,
                    "origin": "selected_preset" if depth == 0 else "inherited_parent",
                    "parent_depth": depth,
                }
                if key == "change_filament_gcode":
                    value = obj[key]
                    if isinstance(value, str):
                        fields[key]["script_sha256"] = hashlib.sha256(
                            value.encode("utf-8")).hexdigest()
                        fields[key]["script_chars"] = len(value)
        parent_name = obj.get("inherits")
        if parent_name:
            if not isinstance(parent_name, str) or len(parent_name) > 200:
                raise SlicerProfileError("Native parent profile reference is invalid.")
            parents = list(SlicerProfile.objects.select_related("file_asset").filter(
                owner_id=current.owner_id, engine=current.engine,
                engine_version=current.engine_version, kind=current.kind,
                name=parent_name, source_scope=current.source_scope,
            )[:2])
            if len(parents) != 1:
                raise SlicerProfileError("Native parent identity is unavailable or ambiguous.")
            current = parents[0]
        else:
            current = None
        depth += 1
    return {
        "profile_kind": str(profile.kind)[:20],
        "inheritance_depth": depth - 1,
        "fields": {
            key: fields.get(key, {"defined": False, "origin": "absent"})
            for key in sorted(_CREALIY_PURGE_ORIGIN_KEYS)
        },
        "verification": "verified_import_chain_not_execution_proof",
    }
