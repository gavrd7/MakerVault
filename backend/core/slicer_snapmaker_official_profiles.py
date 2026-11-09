"""Pinned official Snapmaker Orca native-profile search and candidate import."""
from functools import lru_cache
from pathlib import PurePosixPath

from .slicer_official_filter import narrow_catalogue, models_from_machines, fuzzy_name_match
from .slicer_official_profiles import OfficialProfileError, _get_json

ENGINE = "snapmakerorca"
ENGINE_VERSION = "2.4.1"
SOURCE = "Snapmaker/OrcaSlicer"
REF = "v2.4.1"
BASE = f"https://raw.githubusercontent.com/{SOURCE}/{REF}/resources/profiles"
VENDORS = ("Snapmaker",)
KINDS = {"printer": "machine_list", "filament": "filament_list", "process": "process_list"}
MAX_INDEX = 256 * 1024
MAX_PRESET = 1024 * 1024


@lru_cache(maxsize=4)
def _manifest(vendor="Snapmaker"):
    if vendor not in VENDORS:
        raise OfficialProfileError("Unsupported Snapmaker Orca vendor.")
    manifest, _ = _get_json(BASE + "/" + vendor + ".json", MAX_INDEX)
    for key in KINDS.values():
        if not isinstance(manifest.get(key), list) or len(manifest[key]) > 6000:
            raise OfficialProfileError("Snapmaker native preset catalogue is invalid.")
    return manifest


def available_snapmaker_vendors():
    return [{"id": "Snapmaker", "label": "Snapmaker"}]


def _entries(kind, vendor="Snapmaker"):
    if kind not in KINDS:
        raise OfficialProfileError("Unsupported Snapmaker preset type.")
    prefix = "machine" if kind == "printer" else kind
    result = []
    for row in _manifest(vendor)[KINDS[kind]]:
        if not isinstance(row, dict):
            continue
        name, path = row.get("name"), row.get("sub_path")
        if not isinstance(name, str) or not 1 <= len(name) <= 200 or not isinstance(path, str):
            continue
        parts = PurePosixPath(path)
        if (len(parts.parts) != 2 or parts.parts[0] != prefix or
                parts.suffix.lower() != ".json" or
                any(char in path for char in "\\\\?%#") or
                any(item in {".", ".."} for item in parts.parts)):
            continue
        result.append((name, path))
    return result


def official_catalogue_models(vendor="Snapmaker"):
    return models_from_machines(_entries("printer", vendor))


def search_snapmaker_profiles(query, kind, vendor="Snapmaker", printer_model=None):
    if not isinstance(query, str) or not 2 <= len(query.strip()) <= 80:
        raise OfficialProfileError("Enter two or more search characters.")
    candidates = [(name, path) for name, path in _entries(kind, vendor)
                  if fuzzy_name_match(name, query.strip().casefold())]
    if printer_model:
        candidates = narrow_catalogue(candidates, kind, printer_model)
    return {
        "engine": ENGINE, "engine_version": ENGINE_VERSION, "vendor": vendor,
        "kind": kind, "source": SOURCE, "ref": REF,
        "profiles": [{"name": n, "sub_path": p} for n, p in candidates[:40]],
        "total_matches": len(candidates), "import_status": "candidate_only",
    }


def fetch_snapmaker_profile(kind, name, subpath, vendor="Snapmaker"):
    if (name, subpath) not in _entries(kind, vendor):
        raise OfficialProfileError("Native preset is not in the pinned Snapmaker catalogue.")
    data, raw = _get_json(f"{BASE}/{vendor}/{subpath}", MAX_PRESET)
    expected = "machine" if kind == "printer" else kind
    if data.get("type") != expected:
        raise OfficialProfileError("Upstream Snapmaker preset type differs from the index.")
    if data.get("name") and data["name"] != name:
        raise OfficialProfileError("Upstream Snapmaker preset name differs from the index.")
    return raw
