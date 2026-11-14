"""Bounded inspection of engine-native preset assets; import is not approval.

A profile import never runs the slicer and is always marked candidate.
Actual worker installation, profile inheritance and real compatibility checks
are a separate administrator-reviewed stage.
"""
import hashlib
import json
from pathlib import Path

from .slicer_engines import get_engine


MAX_PROFILE_BYTES = 1024 * 1024
SCRIPT_KEYS = frozenset({"post_process", "post_process_scripts", "post_processing", "post_processing_scripts"})


class SlicerProfileError(ValueError):
    pass


def _extension(asset):
    meta = asset.metadata or {}
    filename = str(meta.get("original_name") or "")
    if filename:
        return Path(filename).suffix.lower()
    extension = str(meta.get("extension") or "").lower()
    if extension:
        return extension
    return Path(str(asset.name)).suffix.lower()


def _check_orca_json(raw):
    try:
        value = json.loads(raw)
    except (ValueError, UnicodeDecodeError):
        raise SlicerProfileError("Orca profile must be valid UTF-8 JSON.") from None
    if not isinstance(value, dict):
        raise SlicerProfileError("Orca profile must be a JSON object.")
    count = 0

    def walk(node, depth=0):
        nonlocal count
        count += 1
        if depth > 12 or count > 10000:
            raise SlicerProfileError("Native profile nesting is too complex.")
        if isinstance(node, dict):
            for key, item in node.items():
                if not isinstance(key, str):
                    raise SlicerProfileError("Invalid native profile property.")
                if key.strip().lower() in SCRIPT_KEYS:
                    raise SlicerProfileError("Post-processing commands are unsupported.")
                walk(item, depth + 1)
        elif isinstance(node, list):
            for item in node:
                walk(item, depth + 1)

    walk(value)
    # Preserve imported child profiles as candidates, but expose that their
    # parent chain must be resolved and approved before worker execution.
    return value


def inspect_native_profile(asset, engine_key):
    engine = get_engine(engine_key)
    extension = ".ini" if engine.profile_format == "prusa-ini" else ".json"
    if _extension(asset) != extension:
        raise SlicerProfileError(f"Use a native {extension} profile for {engine.label}.")
    if not asset.file:
        raise SlicerProfileError("Selected profile has no stored file.")
    try:
        if getattr(asset.file, "_committed", True) is False:
            # Newly imported ContentFile has not been persisted yet. Reading
            # by its provisional name from storage will always fail.
            pending = asset.file.file
            offset = pending.tell()
            try:
                pending.seek(0)
                raw = pending.read(MAX_PROFILE_BYTES + 1)
            finally:
                pending.seek(offset)
        else:
            # Existing encrypted private files must be opened through a fresh
            # storage stream, not a cached FieldFile that may be closed.
            with asset.file.storage.open(asset.file.name, "rb") as stream:
                raw = stream.read(MAX_PROFILE_BYTES + 1)
    except (OSError, ValueError):
        raise SlicerProfileError("Profile contents are unavailable.") from None
    if not raw or len(raw) > MAX_PROFILE_BYTES or b"\x00" in raw:
        raise SlicerProfileError("Profile is empty, binary or exceeds the size limit.")
    try:
        decoded = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise SlicerProfileError("Native profile must use UTF-8 text.") from None
    if engine.profile_format == "prusa-ini":
        if not any("=" in line and not line.lstrip().startswith(("#", ";")) for line in decoded.splitlines()):
            raise SlicerProfileError("Prusa INI profile has no settings.")
        for line in decoded.splitlines():
            stripped = line.lstrip()
            if not stripped or stripped.startswith(("#", ";")):
                continue
            if "=" in stripped and stripped.partition("=")[0].strip().lower() in SCRIPT_KEYS:
                raise SlicerProfileError("Post-processing commands are unsupported.")
    else:
        _check_orca_json(decoded)
    inherits = ""
    if engine.profile_format != "prusa-ini":
        inherits = str(_check_orca_json(decoded).get("inherits") or "")[:200]
    return {
        "sha256": hashlib.sha256(raw).hexdigest(),
        "bytes": len(raw), "extension": extension, "engine": engine.key,
        "inherits": inherits,
        "requires_parent_bundle": bool(inherits),
    }
