"""Import a complete, bounded official native-profile inheritance chain.

Use only the exact pinned Orca/Creality vendor manifests. Never follow
network URLs or arbitrary paths supplied by a preset's 'inherits' field.
Returned parents are ordered base-first and remain unverified candidates.
"""
import json

from .slicer_official_profiles import (
    OfficialProfileError, _entries as orca_entries,
    fetch_official_profile, VENDORS as ORCA_VENDORS,
)
from .slicer_creality_official_profiles import (
    _entries as creality_entries,
    fetch_creality_profile, VENDORS as CREALITY_VENDORS,
)

from .slicer_snapmaker_official_profiles import (
    _entries as snapmaker_entries, fetch_snapmaker_profile,
    VENDORS as SNAPMAKER_VENDORS,
)

MAX_CHAIN = 12
MAX_CHAIN_BYTES = 4 * 1024 * 1024


def official_profile_chain(engine, kind, name, subpath, vendor="Creality", version="2.4.2"):
    """Return [(native_name, pinned_subpath, bytes)] ordered parent-first."""
    if engine not in {"orcaslicer", "crealityprint", "snapmakerorca"}:
        raise OfficialProfileError("Unknown official slicer profile engine.")
    if kind not in {"printer", "filament", "process"}:
        raise OfficialProfileError("Unsupported official profile family.")
    if ((engine == "orcaslicer" and vendor not in ORCA_VENDORS) or
        (engine == "crealityprint" and vendor not in CREALITY_VENDORS) or
        (engine == "snapmakerorca" and vendor not in SNAPMAKER_VENDORS)):
        raise OfficialProfileError("Unsupported official profile vendor for this engine.")
    index = (
        (dict(orca_entries(vendor, kind)) if version == "2.4.2" else
         dict(orca_entries(vendor, kind, version))) if engine == "orcaslicer"
        else dict(creality_entries(kind, vendor)) if engine == "crealityprint"
        else dict(snapmaker_entries(kind, vendor))
    )
    if engine == "orcaslicer":
        fetch = (fetch_official_profile if version == "2.4.2" else
                 lambda profile_kind, profile_name, path, source_vendor:
                 fetch_official_profile(profile_kind, profile_name, path, source_vendor, version))
    else:
        fetch = fetch_creality_profile if engine == "crealityprint" else fetch_snapmaker_profile
    if index.get(name) != subpath:
        raise OfficialProfileError("Requested native profile is not in the pinned catalogue.")
    visiting = set()
    completed = {}
    result = []
    used_bytes = 0

    def resolve(native_name, depth):
        nonlocal used_bytes
        if depth >= MAX_CHAIN or len(result) >= MAX_CHAIN:
            raise OfficialProfileError("Official profile inheritance chain is too deep.")
        if native_name in visiting:
            raise OfficialProfileError("Official profile inheritance is circular.")
        if native_name in completed:
            return
        pinned_path = index.get(native_name)
        if not pinned_path:
            raise OfficialProfileError("Official native parent preset is unavailable: " + native_name[:120])
        visiting.add(native_name)
        try:
            raw = fetch(kind, native_name, pinned_path, vendor)
            used_bytes += len(raw)
            if used_bytes > MAX_CHAIN_BYTES:
                raise OfficialProfileError("Official profile inheritance exceeds the import size limit.")
            try:
                data = json.loads(raw.decode("utf-8-sig"))
            except (ValueError, UnicodeDecodeError):
                raise OfficialProfileError("Official native profile contains invalid JSON.") from None
            if not isinstance(data, dict):
                raise OfficialProfileError("Official native preset must be an object.")
            parent = data.get("inherits")
            if parent:
                if not isinstance(parent, str) or not 1 <= len(parent) <= 200:
                    raise OfficialProfileError("Official native parent identifier is malformed.")
                resolve(parent, depth + 1)
            completed[native_name] = (native_name, pinned_path, raw)
            result.append(completed[native_name])
        finally:
            visiting.discard(native_name)

    resolve(name, 0)
    return result
