"""Pinned official Creality Print native-profile catalogue.

Separate from OrcaSlicer; imported profiles remain unverified candidates.
This source tag is for profile discovery only, not verified CLI execution.
"""
from functools import lru_cache
from pathlib import PurePosixPath

from .slicer_official_profiles import OfficialProfileError, _get_json

ENGINE = "crealityprint"
ENGINE_VERSION = "7.3.0"
SOURCE = "CrealityOfficial/CrealityPrint"
REF = "v7.3.0"
BASE = f"https://raw.githubusercontent.com/{SOURCE}/{REF}/resources/profiles"
KINDS = {"printer": "machine_list", "filament": "filament_list", "process": "process_list"}
MAX_INDEX = 512 * 1024
MAX_PRESET = 1024 * 1024


@lru_cache(maxsize=1)
def _manifest():
    index, _raw = _get_json(BASE + "/Creality.json", MAX_INDEX)
    if index.get("name") != "Creality":
        raise OfficialProfileError("Creality catalogue identity is invalid.")
    for key in KINDS.values():
        if not isinstance(index.get(key), list) or len(index[key]) > 10000:
            raise OfficialProfileError("Creality catalogue has incomplete preset lists.")
    return index


def _entries(kind):
    if kind not in KINDS:
        raise OfficialProfileError("Unknown Creality profile kind.")
    root = "machine" if kind == "printer" else kind
    entries = []
    for row in _manifest()[KINDS[kind]]:
        if not isinstance(row, dict):
            continue
        name, subpath = row.get("name"), row.get("sub_path")
        if not isinstance(name, str) or not 0 < len(name) <= 200 or not isinstance(subpath, str):
            continue
        p = PurePosixPath(subpath)
        if (len(p.parts) != 2 or p.parts[0] != root or p.suffix != ".json"
                or any(c in subpath for c in "\\\\?%#") or any(part in {".", ".."} for part in p.parts)):
            continue
        entries.append((name, subpath))
    return entries


def search_creality_profiles(query, kind, vendor="Creality"):
    if vendor != "Creality" or not isinstance(query, str) or not 2 <= len(query.strip()) <= 80:
        raise OfficialProfileError("Choose Creality and search at least two characters.")
    term = query.strip().casefold()
    matches = [(name, path) for name, path in _entries(kind) if term in name.casefold()]
    return {
        "engine": ENGINE, "engine_version": ENGINE_VERSION,
        "vendor": "Creality", "kind": kind,
        "source": SOURCE, "ref": REF,
        "profiles": [{"name": name, "sub_path": path} for name, path in matches[:40]],
        "total_matches": len(matches),
        "import_status": "candidate_only",
    }


def fetch_creality_profile(kind, name, subpath, vendor="Creality"):
    if vendor != "Creality" or (name, subpath) not in _entries(kind):
        raise OfficialProfileError("Creality preset is not in the pinned catalogue.")
    obj, raw = _get_json(BASE + "/Creality/" + subpath, MAX_PRESET)
    expected = "machine" if kind == "printer" else kind
    if obj.get("type") != expected:
        raise OfficialProfileError("Creality preset type does not match.")
    # Creality's system presets do not consistently include a name property,
    # but the pinned index provides their human-readable identity.
    return raw
