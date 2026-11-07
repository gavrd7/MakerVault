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
        parent = SlicerProfile.objects.select_related("file_asset").filter(
            owner_id=profile.owner_id, engine=profile.engine,
            engine_version=profile.engine_version, kind=profile.kind,
            name=parent_name,
        ).first()
        if not parent:
            raise SlicerProfileError("Native parent preset is missing: " + parent_name)
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
