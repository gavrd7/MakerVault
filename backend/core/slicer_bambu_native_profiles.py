"""Pinned Bambu Studio native slicing presets, separate from machine-model art.

Only official BBL profiles at the reviewed tag can be fetched. Search listings
are not approval to execute. Imports fetch and validate the full same-family
inheritance/include chain before any database records are changed.
"""
import json
from functools import lru_cache
from pathlib import PurePosixPath

from .slicer_bambu_official_profiles import (
    BASE, VENDORS, ENGINE, ENGINE_VERSION, SOURCE, REF,
)
from .slicer_official_filter import fuzzy_name_match
from .slicer_official_profiles import OfficialProfileError, _get_json

KINDS = {"printer": ("machine", "machine_list"),
         "process": ("process", "process_list"),
         "filament": ("filament", "filament_list")}
MAX_INDEX = 512 * 1024
MAX_PROFILE = 1024 * 1024
MAX_CHAIN = 48
MAX_CHAIN_BYTES = 4 * 1024 * 1024


@lru_cache(maxsize=4)
def _entries(kind, vendor="BBL"):
    if kind not in KINDS or vendor not in VENDORS:
        raise OfficialProfileError("Unknown Bambu native profile family or vendor.")
    directory, key = KINDS[kind]
    index, _ = _get_json(f"{BASE}/{vendor}.json", MAX_INDEX)
    rows = index.get(key)
    if not isinstance(rows, list) or len(rows) > 5000:
        raise OfficialProfileError("Official Bambu native profile catalogue is unavailable.")
    result = {}
    for item in rows:
        if not isinstance(item, dict):
            continue
        name, path = item.get("name"), item.get("sub_path")
        if not isinstance(name, str) or not 1 <= len(name) <= 200 or not isinstance(path, str):
            continue
        route = PurePosixPath(path)
        if (not 2 <= len(route.parts) <= 4 or route.parts[0] != directory
                or route.suffix.lower() != ".json"
                or any(ch in path for ch in "\\\\?%#")
                or any(part in (".", "..", "") for part in route.parts)):
            continue
        if name in result and result[name] != path:
            raise OfficialProfileError("Official Bambu preset index has ambiguous names.")
        result[name] = path
    return result


def search_bambu_native_profiles(query, kind, vendor="BBL", printer_model=None):
    if not isinstance(query, str) or len(query.strip()) > 80:
        raise OfficialProfileError("Search for at least two characters.")
    entries = _entries(kind, vendor)
    needle = query.strip().casefold()
    matches = [(name, path) for name, path in entries.items()
               if (not needle or fuzzy_name_match(name, needle))
               and not name.startswith("fdm_")
               and " template " not in name]
    if printer_model and kind == "printer":
        matches = [(name, path) for name, path in matches
                   if name.casefold().startswith(printer_model.casefold())]
    matches.sort(key=lambda item: item[0].casefold())
    return {
        "engine": ENGINE, "engine_version": ENGINE_VERSION, "vendor": vendor,
        "kind": kind, "source": SOURCE, "ref": REF,
        "profiles": [{"name": name, "sub_path": path} for name, path in matches[:40]],
        "total_matches": len(matches), "import_status": "candidate_only",
        "model_artwork_only": False,
    }


def fetch_bambu_native_chain(kind, name, subpath, vendor="BBL", *, version=ENGINE_VERSION):
    """Return (name, pinned_index_path, raw_json) in base-first import order."""
    if version != ENGINE_VERSION or kind not in KINDS:
        raise OfficialProfileError("Bambu native presets require the reviewed exact engine release.")
    index = _entries(kind, vendor)
    if index.get(name) != subpath:
        raise OfficialProfileError("Requested Bambu native preset is not in the pinned vendor index.")
    requested_name = name
    result = []
    visiting = set()
    complete = {}
    used = 0
    type_expected = KINDS[kind][0]

    def walk(current, depth, *, included=False):
        nonlocal used
        if depth >= MAX_CHAIN or len(result) >= MAX_CHAIN:
            raise OfficialProfileError("Bambu native profile chain is too large.")
        if current in visiting:
            raise OfficialProfileError("Bambu native profile inheritance is circular.")
        if current in complete:
            if not included and complete[current].get("type") != type_expected:
                raise OfficialProfileError("Typeless Bambu included template cannot become a preset parent.")
            return
        path = index.get(current)
        if not path:
            raise OfficialProfileError("Pinned Bambu native dependency is unavailable.")
        visiting.add(current)
        try:
            document, raw = _get_json(f"{BASE}/{vendor}/{path}", MAX_PROFILE)
            used += len(raw)
            if used > MAX_CHAIN_BYTES:
                raise OfficialProfileError("Bambu native dependency bundle exceeds the size limit.")
            if (not isinstance(document, dict) or document.get("name") != current
                    or (document.get("type") != type_expected
                        and not (included and document.get("type") is None))):
                raise OfficialProfileError("Pinned Bambu native profile identity mismatch.")
            if current == requested_name and document.get("instantiation") != "true":
                raise OfficialProfileError("Bambu native preset is not an instantiable profile.")
            parent = document.get("inherits", "")
            if parent and (not isinstance(parent, str) or len(parent) > 200):
                raise OfficialProfileError("Bambu native inheritance is malformed.")
            if parent:
                walk(parent, depth + 1)
            included_names = document.get("include", [])
            if (not isinstance(included_names, list)
                    or len(included_names) > 16
                    or any(not isinstance(x, str) or not 1 <= len(x) <= 200
                           for x in included_names)):
                raise OfficialProfileError("Bambu native included templates are invalid.")
            for ref_name in included_names:
                walk(ref_name, depth + 1, included=True)
            complete[current] = document
            result.append((current, path, raw))
        finally:
            visiting.discard(current)

    walk(name, 0)
    return result
