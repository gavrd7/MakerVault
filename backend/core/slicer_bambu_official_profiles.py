"""Read-only official Bambu Studio printer-model catalogue at a reviewed tag.

These are model/artwork metadata records, NOT executable machine profiles.
Slicer installation, device compatibility and actual slice execution remain
separate. Never accept a user-supplied upstream URL or version.
"""
from functools import lru_cache
from pathlib import PurePosixPath

from .slicer_official_profiles import OfficialProfileError, _get_json
from .slicer_official_filter import fuzzy_name_match

ENGINE = "bambustudio"
ENGINE_VERSION = "02.09.01.70"
SOURCE = "bambulab/BambuStudio"
REF = "v02.09.01.70"
BASE = f"https://raw.githubusercontent.com/{SOURCE}/{REF}/resources/profiles"
VENDORS = ("BBL",)
MAX_INDEX = 512 * 1024
MAX_MODEL = 256 * 1024


@lru_cache(maxsize=4)
def _entries(vendor="BBL"):
    if vendor not in VENDORS:
        raise OfficialProfileError("Unknown Bambu official profile vendor.")
    index, _ = _get_json(f"{BASE}/{vendor}.json", MAX_INDEX)
    models = index.get("machine_model_list")
    if not isinstance(models, list) or len(models) > 1000:
        raise OfficialProfileError("Bambu vendor model catalogue is unavailable.")
    result = {}
    for row in models:
        if not isinstance(row, dict):
            continue
        name, path = row.get("name"), row.get("sub_path")
        if not isinstance(name, str) or not 1 <= len(name) <= 200 or not isinstance(path, str):
            continue
        route = PurePosixPath(path)
        if (len(route.parts) != 2 or route.parts[0] != "machine"
                or route.suffix.lower() != ".json"
                or any(char in path for char in "\\\\?%#")
                or any(part in (".", "..") for part in route.parts)):
            continue
        if name in result and result[name] != path:
            raise OfficialProfileError("Ambiguous Bambu machine model.")
        result[name] = path
    return result


def available_bambu_vendors():
    return [{"id": "BBL", "label": "Bambu Lab"}]


def official_catalogue_models(vendor="BBL"):
    return sorted(_entries(vendor), key=str.casefold)


def search_bambu_profiles(query, kind, vendor="BBL", printer_model=None):
    if kind != "printer":
        raise OfficialProfileError("Bambu model-artwork discovery currently supports printer models only.")
    if not isinstance(query, str) or not 2 <= len(query.strip()) <= 80:
        raise OfficialProfileError("Search for at least two characters.")
    entries = _entries(vendor)
    candidates = [(name, path) for name, path in entries.items()
                  if fuzzy_name_match(name, query.strip().casefold())]
    if printer_model:
        candidates = [(name, path) for name, path in candidates if name == printer_model]
    return {
        "engine": ENGINE, "engine_version": ENGINE_VERSION, "vendor": vendor,
        "kind": kind, "source": SOURCE, "ref": REF,
        "profiles": [{"name": n, "sub_path": p} for n, p in candidates[:40]],
        "total_matches": len(candidates), "import_status": "candidate_only",
        "model_artwork_only": True,
    }


def fetch_bambu_model(kind, name, subpath, vendor="BBL"):
    if kind != "printer" or _entries(vendor).get(name) != subpath:
        raise OfficialProfileError("Bambu model is not in the reviewed vendor index.")
    data, raw = _get_json(f"{BASE}/{vendor}/{subpath}", MAX_MODEL)
    if data.get("type") != "machine_model" or data.get("name") != name:
        raise OfficialProfileError("Bambu model identity does not match its index.")
    return raw
