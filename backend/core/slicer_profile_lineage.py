"""Read-only OrcaSlicer native profile lineage inspection.

No flattening or executable approval. Exact imported, same-owner native
profile sources are checked against their registered hashes. A complete
dependency *graph* is not evidence that the effective profile was validated.
"""
import hashlib
from .slicer_profiles import MAX_PROFILE_BYTES, SlicerProfileError, _check_orca_json


MAX_DEPTH = 12


def _inspect_source(record):
    if record.engine not in {"orcaslicer", "crealityprint"}:
        raise SlicerProfileError("Native JSON profile inspection requires Orca or Creality Print.")
    if not record.file_asset.file:
        raise SlicerProfileError("Native profile file is unavailable.")
    try:
        with record.file_asset.file.open("rb") as stream:
            raw = stream.read(MAX_PROFILE_BYTES + 1)
    except (OSError, ValueError):
        raise SlicerProfileError("Native profile file cannot be read.") from None
    if not raw or len(raw) > MAX_PROFILE_BYTES:
        raise SlicerProfileError("Native profile is empty or exceeds the size limit.")
    if hashlib.sha256(raw).hexdigest() != record.content_sha256:
        raise SlicerProfileError("Native profile contents changed after registration.")
    try:
        data = _check_orca_json(raw.decode("utf-8-sig"))
    except UnicodeDecodeError:
        raise SlicerProfileError("Native profile must be UTF-8.") from None
    declared_name = data.get("name")
    if declared_name and declared_name != record.name:
        raise SlicerProfileError("Native preset name differs from its registered identity.")
    return data


def inspect_orca_lineage(start, candidates):
    """Return the intact parent chain; reject cycles/ambiguity across owners.

    start and candidates are trusted SlicerProfile model records, not request
    JSON. A missing parent is reported, not invented or inherited by guesswork.
    """
    if start.engine != "orcaslicer":
        raise SlicerProfileError("Only Orca profile inheritance can be inspected.")
    by_name = {}
    for candidate in candidates:
        if (
            candidate.owner_id != start.owner_id
            or candidate.engine != start.engine
            or candidate.engine_version != start.engine_version
            or candidate.kind != start.kind
        ):
            continue
        if candidate.name in by_name:
            raise SlicerProfileError("Ambiguous native parent preset identity.")
        by_name[candidate.name] = candidate
    by_name.setdefault(start.name, start)
    chain = []
    visited = set()
    item = start
    while item:
        if item.name in visited:
            return {
                "status": "cycle", "chain": chain, "missing": None,
                "approved_for_execution": False,
            }
        if len(chain) >= MAX_DEPTH:
            return {
                "status": "too_deep", "chain": chain, "missing": None,
                "approved_for_execution": False,
            }
        visited.add(item.name)
        try:
            data = _inspect_source(item)
        except SlicerProfileError as exc:
            return {
                "status": "invalid", "chain": chain, "missing": None,
                "error": str(exc), "approved_for_execution": False,
            }
        parent = data.get("inherits")
        if parent and (not isinstance(parent, str) or len(parent) > 200):
            return {
                "status": "invalid", "chain": chain, "missing": None,
                "error": "Invalid native parent preset identity.",
                "approved_for_execution": False,
            }
        chain.append({
            "id": str(item.pk), "name": item.name, "kind": item.kind,
            "checksum": item.content_sha256, "status": item.status,
            "inherits": parent or None,
        })
        if not parent:
            return {
                "status": "complete", "chain": chain, "missing": None,
                "approved_for_execution": False,
            }
        item = by_name.get(parent)
        if item is None:
            return {
                "status": "missing", "chain": chain, "missing": parent,
                "approved_for_execution": False,
            }
    raise SlicerProfileError("Invalid native profile lineage.")
