"""Official Orca native-profile discovery and opt-in candidate import.

Only a pinned official repository/tag and a fixed list of vendor manifests
are used. No arbitrary network URL, user-selected ref or untrusted redirect.
Source authenticity is not execution approval: every import stays candidate.
"""
from functools import lru_cache
from pathlib import PurePosixPath

from .slicer_official_filter import narrow_catalogue, models_from_machines, fuzzy_name_match

import requests

from .slicer_profiles import SlicerProfileError, _check_orca_json

ENGINE = "orcaslicer"
ENGINE_VERSION = "2.4.2"
SOURCE = "OrcaSlicer/OrcaSlicer"
REF = "v2.4.2"
BASE = f"https://raw.githubusercontent.com/{SOURCE}/{REF}/resources/profiles"
# Exact upstream v2.4.2 vendor manifest names, not printer allowlisting.
# Each import remains a non-executable candidate until separately verified.
VENDORS = ("Afinia", "Anker", "Anycubic", "Artillery", "BBL", "BIQU", "Blocks", "CONSTRUCT3D", "Chuanying", "Co Print", "CoLiDo", "Comgrow", "Creality", "Cubicon", "Custom", "DeltaMaker", "Dremel", "Elegoo", "Eryone", "FLSun", "Flashforge", "FlyingBear", "Folgertech", "Geeetech", "Ginger Additive", "InfiMech", "Kingroon", "LH", "LONGER", "Lulzbot", "M3D", "MagicMaker", "Mellow", "OpenEYE", "OrcaArena", "OrcaFilamentLibrary", "Peopoly", "Phrozen", "Positron3D", "Prusa", "Qidi", "RH3D", "Raise3D", "Ratrig", "RolohaunDesign", "SecKit", "SeeMeCNC", "Snapmaker", "Sovol", "Tiertime", "Tronxy", "TwoTrees", "UltiMaker", "Vivedino", "Volumic", "Voron", "Voxelab", "Vzbot", "WEMAKE3D", "Wanhao France", "Wanhao", "WonderMaker", "Z-Bolt", "iQ", "re3D",)
KINDS = {"printer": "machine_list", "filament": "filament_list", "process": "process_list"}
MAX_INDEX = 512 * 1024
MAX_PRESET = 1024 * 1024


class OfficialProfileError(ValueError):
    pass


def _get_json(url, maximum):
    try:
        response = requests.get(
            url, timeout=(3, 12), allow_redirects=False,
            headers={"Accept": "application/json", "User-Agent": "MakerVault-OfficialProfileBrowser/1"},
            stream=True,
        )
        try:
            if response.status_code != 200:
                raise OfficialProfileError("Official profile source is not currently available.")
            declared = response.headers.get("Content-Length")
            if declared and int(declared) > maximum:
                raise OfficialProfileError("Official profile source exceeds its size limit.")
            content = bytearray()
            for chunk in response.iter_content(65536):
                content.extend(chunk)
                if len(content) > maximum:
                    raise OfficialProfileError("Official profile source exceeds its size limit.")
            raw = bytes(content)
        finally:
            response.close()
    except (requests.RequestException, ValueError) as exc:
        if isinstance(exc, OfficialProfileError):
            raise
        raise OfficialProfileError("Could not contact the pinned official profile source.") from exc
    try:
        value = _check_orca_json(raw.decode("utf-8-sig"))
    except (UnicodeDecodeError, SlicerProfileError) as exc:
        raise OfficialProfileError("Official profile JSON is invalid.") from exc
    return value, raw


@lru_cache(maxsize=8)
def _manifest(vendor):
    if vendor not in VENDORS:
        raise OfficialProfileError("Official vendor is not supported yet.")
    index, raw = _get_json(BASE + "/" + vendor + ".json", MAX_INDEX)
    if not isinstance(index.get("name"), str) or not 1 <= len(index["name"]) <= 100:
        raise OfficialProfileError("Official vendor index identity is invalid.")
    for kind, key in KINDS.items():
        if not isinstance(index.get(key), list) or len(index[key]) > 5000:
            raise OfficialProfileError("Official vendor index is incomplete or oversized.")
    return index


def available_official_vendors():
    """Pinned Orca catalogues; no host probing or automatic download."""
    return [{"id": name, "label": name} for name in VENDORS]


def _entries(vendor, kind):
    if kind not in KINDS:
        raise OfficialProfileError("Unknown native profile kind.")
    entries = []
    for record in _manifest(vendor)[KINDS[kind]]:
        if not isinstance(record, dict):
            continue
        name, subpath = record.get("name"), record.get("sub_path")
        if not isinstance(name, str) or not 0 < len(name) <= 200:
            continue
        if not isinstance(subpath, str):
            continue
        path = PurePosixPath(subpath)
        expected = "machine" if kind == "printer" else kind
        if (
            len(path.parts) != 2 or path.parts[0] != expected
            or path.suffix != ".json" or any(part in (".", "..") for part in path.parts)
            or any(c in subpath for c in "\\\\?%#")
        ):
            continue
        entries.append((name, subpath))
    return entries


def official_catalogue_models(vendor="Creality"):
    return models_from_machines(_entries(vendor, "printer"))


def search_official_profiles(query, kind, vendor="Creality", printer_model=None):
    if not isinstance(query, str) or not 2 <= len(query.strip()) <= 80:
        raise OfficialProfileError("Search using at least two characters.")
    if not isinstance(vendor, str) or vendor not in VENDORS:
        raise OfficialProfileError("Choose an available official profile vendor.")
    term = query.strip().casefold()
    matches = [(name, subpath) for name, subpath in _entries(vendor, kind) if fuzzy_name_match(name, term)]
    if printer_model:
        matches = narrow_catalogue(matches, kind, printer_model)
    return {
        "engine": ENGINE, "engine_version": ENGINE_VERSION, "vendor": vendor,
        "kind": kind, "source": SOURCE, "ref": REF,
        "profiles": [{"name": name, "sub_path": path} for name, path in matches[:40]],
        "total_matches": len(matches),
        "import_status": "candidate_only",
    }


def fetch_official_profile(kind, name, subpath, vendor="Creality"):
    if vendor not in VENDORS:
        raise OfficialProfileError("Unsupported official profile vendor.")
    if (name, subpath) not in _entries(vendor, kind):
        raise OfficialProfileError("Preset is not present in the pinned official catalogue.")
    profile, raw = _get_json(BASE + "/" + vendor + "/" + subpath, MAX_PRESET)
    if profile.get("name") != name:
        raise OfficialProfileError("Official preset identity does not match the catalogue.")
    expected_kind = "machine" if kind == "printer" else kind
    if profile.get("type") != expected_kind:
        raise OfficialProfileError("Official native preset kind does not match.")
    return raw
