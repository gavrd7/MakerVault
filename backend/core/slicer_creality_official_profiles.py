"""Pinned official Creality Print native-profile catalogue.

Separate from OrcaSlicer; imported profiles remain unverified candidates.
Profile sources follow the pinned Creality Print release, not printer brands.
This source tag is for profile discovery only, not verified CLI execution.
"""
from functools import lru_cache
from pathlib import PurePosixPath

from .slicer_official_filter import narrow_catalogue, models_from_machines, fuzzy_name_match

from .slicer_official_profiles import OfficialProfileError, _get_json

ENGINE = "crealityprint"
ENGINE_VERSION = "7.3.0"
SOURCE = "CrealityOfficial/CrealityPrint"
REF = "v7.3.0"
BASE = f"https://raw.githubusercontent.com/{SOURCE}/{REF}/resources/profiles"
# Pinned v7.3.0 manifest basenames, excluding non-profile metadata JSON.
VENDORS = ("Anker", "Anycubic", "Artillery", "BBL", "BIQU", "CONSTRUCT3D", "Comgrow", "Creality", "Custom", "Dremel", "Elegoo", "FLSun", "Flashforge", "FlyingBear", "Folgertech", "InfiMech", "Kingroon", "MagicMaker", "OrcaArena", "Peopoly", "Positron3D", "Prusa", "Qidi", "Raise3D", "Ratrig", "SecKit", "Snapmaker", "Sovol", "Tronxy", "TwoTrees", "UltiMaker", "Vivedino", "Voron", "Voxelab", "Vzbot", "Wanhao",)
KINDS = {"printer": "machine_list", "filament": "filament_list", "process": "process_list"}
MAX_INDEX = 512 * 1024
MAX_PRESET = 1024 * 1024


@lru_cache(maxsize=16)
def _manifest(vendor="Creality"):
    if vendor not in VENDORS:
        raise OfficialProfileError("Unsupported pinned Creality Print manufacturer catalogue.")
    index, _raw = _get_json(BASE + "/" + vendor + ".json", MAX_INDEX)
    if not isinstance(index.get("name"), str) or not 1 <= len(index["name"]) <= 100:
        raise OfficialProfileError("Upstream catalogue identity is invalid.")
    for key in KINDS.values():
        if not isinstance(index.get(key), list) or len(index[key]) > 10000:
            raise OfficialProfileError("Creality catalogue has incomplete preset lists.")
    return index


def available_creality_vendors():
    """Pinned native Creality Print profile sources; not printer compatibility claims."""
    return [{"id": vendor, "label": vendor} for vendor in VENDORS]


def _entries(kind, vendor="Creality"):
    if kind not in KINDS:
        raise OfficialProfileError("Unknown Creality profile kind.")
    root = "machine" if kind == "printer" else kind
    entries = []
    for row in _manifest(vendor)[KINDS[kind]]:
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


def official_catalogue_models(vendor="Creality"):
    return models_from_machines(_entries("printer", vendor))


def search_creality_profiles(query, kind, vendor="Creality", printer_model=None):
    if vendor not in VENDORS or not isinstance(query, str) or not 2 <= len(query.strip()) <= 80:
        raise OfficialProfileError("Choose an upstream manufacturer catalogue and search at least two characters.")
    term = query.strip().casefold()
    matches = [(name, path) for name, path in _entries(kind, vendor) if fuzzy_name_match(name, term)]
    if printer_model:
        matches = narrow_catalogue(matches, kind, printer_model)
    return {
        "engine": ENGINE, "engine_version": ENGINE_VERSION,
        "vendor": vendor, "kind": kind,
        "source": SOURCE, "ref": REF,
        "profiles": [{"name": name, "sub_path": path} for name, path in matches[:40]],
        "total_matches": len(matches),
        "import_status": "candidate_only",
    }


def fetch_creality_profile(kind, name, subpath, vendor="Creality"):
    if vendor not in VENDORS or (name, subpath) not in _entries(kind, vendor):
        raise OfficialProfileError("Native preset is not in the pinned engine catalogue.")
    obj, raw = _get_json(BASE + "/" + vendor + "/" + subpath, MAX_PRESET)
    expected = "machine" if kind == "printer" else kind
    if obj.get("type") != expected:
        raise OfficialProfileError("Creality preset type does not match.")
    # Creality's system presets do not consistently include a name property,
    # but the pinned index provides their human-readable identity.
    return raw
