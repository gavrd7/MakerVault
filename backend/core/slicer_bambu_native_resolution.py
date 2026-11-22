"""Resolve imported Bambu native presets under exact owner/version/vendor scope.

The official BBL machine/process/filament profiles contain native inherits
and include references. Flatten only records already imported from the exact
same pinned source. No upstream fetch or implicit profile substitution happens
when a slice is requested.
"""
import hashlib
import json

from .models import SlicerProfile
from .slicer_profiles import SlicerProfileError, _check_orca_json

KIND_TYPES = {"printer": "machine", "process": "process", "filament": "filament"}
MAX_BYTES = 1024 * 1024
MAX_CHAIN = 48
MAX_CHAIN_BYTES = 4 * 1024 * 1024


def flatten_bambu_preset(name, kind, fetch):
    """Pure function to assemble an indexed native same-family preset."""
    if kind not in KIND_TYPES or not isinstance(name, str) or not 1 <= len(name) <= 200:
        raise SlicerProfileError("Unsupported Bambu profile identity.")
    native_type = KIND_TYPES[kind]
    result_cache = {}
    source_types = {}
    visiting = set()
    total = 0

    def visit(current, depth, included=False):
        nonlocal total
        if current in visiting or depth >= MAX_CHAIN or len(result_cache) >= MAX_CHAIN:
            raise SlicerProfileError("Bambu native dependency cycle or excessive depth.")
        if current in result_cache:
            if not included and source_types[current] != native_type:
                raise SlicerProfileError("Typeless included template is not a native preset.")
            return dict(result_cache[current])
        visiting.add(current)
        try:
            raw = fetch(current)
            if not isinstance(raw, bytes) or not 0 < len(raw) <= MAX_BYTES:
                raise SlicerProfileError("Bambu native dependency is empty or too large.")
            total += len(raw)
            if total > MAX_CHAIN_BYTES:
                raise SlicerProfileError("Bambu native dependency expansion exceeds limits.")
            try:
                data = _check_orca_json(raw.decode("utf-8-sig"))
            except UnicodeError:
                raise SlicerProfileError("Bambu native profile must use UTF-8 JSON.") from None
            if data.get("name") != current:
                raise SlicerProfileError("Bambu dependency name differs from its imported identity.")
            observed_type = data.get("type")
            if observed_type != native_type and not (included and observed_type is None):
                raise SlicerProfileError("Bambu native dependency type does not match profile family.")
            if current == name and data.get("instantiation") != "true":
                raise SlicerProfileError("Bambu selected profile must be an instantiable preset.")
            parent = data.get("inherits", "")
            if parent and (not isinstance(parent, str) or not 1 <= len(parent) <= 200):
                raise SlicerProfileError("Bambu native parent identity is invalid.")
            references = data.get("include", [])
            if (not isinstance(references, list) or len(references) > 16
                    or any(not isinstance(x, str) or not 1 <= len(x) <= 200 for x in references)):
                raise SlicerProfileError("Bambu native include identities are invalid.")
            merged = visit(parent, depth+1) if parent else {}
            for template in references:
                merged.update(visit(template, depth+1, included=True))
            merged.update({key:value for key,value in data.items()
                           if key not in {"inherits", "include"}})
            result_cache[current] = dict(merged)
            source_types[current] = observed_type
            return merged
        finally:
            visiting.remove(current)

    output = visit(name, 0)
    output.pop("inherits", None)
    output.pop("include", None)
    if output.get("type") != native_type or output.get("name") != name:
        raise SlicerProfileError("Bambu native resolved identity is invalid.")
    raw = (json.dumps(output, separators=(",", ":"), ensure_ascii=False)).encode("utf-8")
    if len(raw) > MAX_BYTES:
        raise SlicerProfileError("Bambu native resolved preset exceeds worker limits.")
    _check_orca_json(raw.decode())
    return raw


def resolved_bambu_profile(profile):
    """Resolve one owned, exact-release imported Bambu profile."""
    if (profile.engine != "bambustudio"
            or profile.kind not in KIND_TYPES
            or profile.engine_version != "02.09.01.70"
            or not profile.source_scope.startswith("bambulab/BambuStudio@v02.09.01.70/BBL")):
        raise SlicerProfileError("Unapproved Bambu native profile source or version.")
    def fetch(current):
        if current == profile.name:
            item = profile
        else:
            rows = list(SlicerProfile.objects.select_related("file_asset").filter(
                owner_id=profile.owner_id, engine="bambustudio",
                engine_version=profile.engine_version, kind=profile.kind,
                source_scope=profile.source_scope, name=current,
            )[:2])
            if len(rows) != 1:
                raise SlicerProfileError("Pinned Bambu native parent/include is absent or ambiguous.")
            item = rows[0]
        if not item.file_asset.file or item.file_asset.owner_id != profile.owner_id:
            raise SlicerProfileError("Bambu native profile is not owned or available.")
        with item.file_asset.file.storage.open(item.file_asset.file.name, "rb") as stream:
            data = stream.read(MAX_BYTES + 1)
        if not data or len(data)>MAX_BYTES or hashlib.sha256(data).hexdigest()!=item.content_sha256:
            raise SlicerProfileError("Bambu native profile bytes differ from imported checksum.")
        return data
    return flatten_bambu_preset(profile.name, profile.kind, fetch)
