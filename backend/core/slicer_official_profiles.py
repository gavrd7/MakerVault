"""Official Orca native-profile discovery and opt-in candidate import.

Only a pinned official repository/tag and a fixed list of vendor manifests
are used. No arbitrary network URL, user-selected ref or untrusted redirect.
Source authenticity is not execution approval: every import stays candidate.
"""
from functools import lru_cache
from concurrent.futures import ThreadPoolExecutor
from pathlib import PurePosixPath

from .slicer_official_filter import narrow_catalogue, models_from_machines, fuzzy_name_match, slot_filament_catalogue

import requests

from .slicer_profiles import SlicerProfileError, _check_orca_json

ENGINE = "orcaslicer"
ENGINE_VERSION = "2.4.2"  # Legacy default; explicit imports select a pinned engine version.
APPROVED_VERSIONS = ("2.4.2", "2.5.0")
SOURCE = "OrcaSlicer/OrcaSlicer"
REF = "v2.4.2"
BASE = f"https://raw.githubusercontent.com/{SOURCE}/{REF}/resources/profiles"
FILAMENT_LIBRARY = "OrcaFilamentLibrary"

def _ref(version):
    if version not in APPROVED_VERSIONS:
        raise OfficialProfileError("Only pinned OrcaSlicer 2.4.2 or 2.5.0 profiles can be imported.")
    return "v" + version

def _base(version):
    return f"https://raw.githubusercontent.com/{SOURCE}/{_ref(version)}/resources/profiles"
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


@lru_cache(maxsize=128)
def _manifest(vendor, version=ENGINE_VERSION):
    if vendor not in VENDORS:
        raise OfficialProfileError("Official vendor is not supported yet.")
    index, raw = _get_json(_base(version) + "/" + vendor + ".json", MAX_INDEX)
    if not isinstance(index.get("name"), str) or not 1 <= len(index["name"]) <= 100:
        raise OfficialProfileError("Official vendor index identity is invalid.")
    for kind, key in KINDS.items():
        if not isinstance(index.get(key), list) or len(index[key]) > 5000:
            raise OfficialProfileError("Official vendor index is incomplete or oversized.")
    return index


def available_official_vendors(version=ENGINE_VERSION):
    """Pinned Orca catalogues; no host probing or automatic download."""
    _ref(version)
    return [{"id": name, "label": "Filament manufacturers (Orca library)" if name == FILAMENT_LIBRARY else name} for name in VENDORS]


def _entries(vendor, kind, version=ENGINE_VERSION):
    if kind not in KINDS:
        raise OfficialProfileError("Unknown native profile kind.")
    entries = []
    for record in _manifest(vendor, version)[KINDS[kind]]:
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
            not 2 <= len(path.parts) <= 4 or path.parts[0] != expected
            or path.suffix != ".json" or any(part in (".", "..") for part in path.parts)
            or any(c in subpath for c in "\\\\?%#") or not all(part.strip() == part for part in path.parts)
        ):
            continue
        entries.append((name, subpath))
    return entries


def official_catalogue_models(vendor="Creality", version=ENGINE_VERSION):
    return models_from_machines(_entries(vendor, "printer", version))


def official_filament_brands(version=ENGINE_VERSION):
    """Manufacturer folders found in the version-pinned native filament library."""
    entries = _entries(FILAMENT_LIBRARY, "filament", version)
    return sorted({path.split("/")[1] for _name, path in entries
                   if len(path.split("/")) == 3 and path.split("/")[1] != "base"}, key=str.casefold)



def all_official_filament_manufacturers(version=ENGINE_VERSION):
    """Unified native filament brands, including printer-maker catalogues.

    The dedicated Orca filament library is not the entirety of upstream
    filament presets: Creality, Elegoo, Prusa and other manufacturers also
    publish filament_list entries under their own pinned vendor manifests.
    Catalogue ids are never used as a substitute for native profile identity.
    """
    _ref(version)
    library_brands = official_filament_brands(version)
    return sorted(set(library_brands).union(
        vendor for vendor in VENDORS if vendor != FILAMENT_LIBRARY
    ), key=str.casefold)


def search_all_official_filaments(query="", *, brand="", version=ENGINE_VERSION,
                                 offset=0, printer_model=None):
    """Browse native filament entries across official pinned Orca catalogues.

    Return each entry with its *actual* source vendor for secure opt-in import
    and parent-chain resolution. Do not assume printer-brand == filament-brand
    and never download a preset from a user-supplied host or URL.
    """
    _ref(version)
    if not isinstance(query, str) or len(query.strip()) > 80:
        raise OfficialProfileError("Search must be 80 characters or fewer.")
    if type(offset) is not int or offset < 0 or offset > 400000:
        raise OfficialProfileError("Invalid official filament result offset.")
    if brand and brand not in all_official_filament_manufacturers(version):
        raise OfficialProfileError("Select a listed filament manufacturer.")
    # Selected manufacturer: browse both its Orca library directory and,
    # when available, the printer maker's own official filament catalogue.
    # 'All manufacturers' requests the full bounded upstream manifest set.
    catalogues = ([FILAMENT_LIBRARY] + [
        vendor for vendor in VENDORS
        if vendor != FILAMENT_LIBRARY and
        (not brand or vendor.casefold() == brand.casefold() or
         (brand.casefold() in ("bambu", "bambu lab") and vendor == "BBL"))
    ])
    def collect(vendor):
        try:
            entries = _entries(vendor, "filament", version)
            return vendor, entries, None
        except OfficialProfileError as exc:
            return vendor, [], str(exc)
    # Bounded parallel retrieval and per-release _manifest cache. A single
    # temporarily unavailable manufacturer must not hide the other catalogues.
    with ThreadPoolExecutor(max_workers=12) as pool:
        collected = list(pool.map(collect, catalogues))
    if collected and all(problem for _, _, problem in collected):
        raise OfficialProfileError("Official filament catalogue sources are not currently available.")
    matches = []
    term = query.strip()
    for vendor, entries, _problem in collected:
        for name, subpath in entries:
            if vendor == FILAMENT_LIBRARY and brand and not subpath.startswith(
                    "filament/" + brand + "/"):
                continue
            if term and not fuzzy_name_match(name, term):
                continue
            if printer_model and not narrow_catalogue(
                    [(name, subpath)], "filament", printer_model):
                continue
            matches.append({"name": name, "sub_path": subpath, "vendor": vendor})
    matches.sort(key=lambda row: (row["name"].casefold(), row["vendor"].casefold(),
                                  row["sub_path"].casefold()))
    return {
        "engine": ENGINE, "engine_version": version, "kind": "filament",
        "vendor": "All filament manufacturers" if not brand else brand,
        "source": SOURCE, "ref": _ref(version), "brand": brand,
        "profiles": matches[offset:offset + 40],
        "total_matches": len(matches),
        "import_status": "candidate_only",
        "partial_catalogues": sum(bool(problem) for _, _, problem in collected),
    }


def search_official_profiles(query, kind, vendor="Creality", printer_model=None,
                             version=ENGINE_VERSION, brand="", slot_discovery=False,
                             material="", manufacturer="", offset=0):
    if not isinstance(query, str) or len(query.strip()) > 80:
        raise OfficialProfileError("Search must be 80 characters or fewer.")
    if not isinstance(vendor, str) or vendor not in VENDORS:
        raise OfficialProfileError("Choose an available official profile vendor.")
    _ref(version)
    if brand and (kind != "filament" or vendor != FILAMENT_LIBRARY or
                  brand not in official_filament_brands(version)):
        raise OfficialProfileError("Select a listed filament manufacturer.")
    term = query.strip().casefold()
    matches = [(name, subpath) for name, subpath in _entries(vendor, kind, version)
               if (not term or fuzzy_name_match(name, term)) and
               (not brand or subpath.startswith("filament/" + brand + "/"))]
    if slot_discovery:
        if kind != "filament" or not printer_model:
            raise OfficialProfileError("Slot discovery requires an identified printer and filament kind.")
        # Search by product name and material separately; otherwise catalogue
        # truncation or a broad vendor token can hide the compatible result.
        all_entries = _entries(vendor, kind, version)
        matches = slot_filament_catalogue(
            all_entries, printer_model, product=query, material=material,
            manufacturer=manufacturer, catalogue_vendor=vendor)
    elif printer_model:
        matches = narrow_catalogue(matches, kind, printer_model)
    return {
        "engine": ENGINE, "engine_version": version, "vendor": vendor,
        "kind": kind, "source": SOURCE, "ref": _ref(version), "brand": brand,
        "profiles": [{"name": name, "sub_path": path} for name, path in matches[offset:offset + 40]],
        "total_matches": len(matches),
        "import_status": "candidate_only",
    }


def fetch_official_profile(kind, name, subpath, vendor="Creality", version=ENGINE_VERSION):
    if vendor not in VENDORS:
        raise OfficialProfileError("Unsupported official profile vendor.")
    if (name, subpath) not in _entries(vendor, kind, version):
        raise OfficialProfileError("Preset is not present in the pinned official catalogue.")
    profile, raw = _get_json(_base(version) + "/" + vendor + "/" + subpath, MAX_PRESET)
    if profile.get("name") != name:
        raise OfficialProfileError("Official preset identity does not match the catalogue.")
    expected_kind = "machine" if kind == "printer" else kind
    if profile.get("type") != expected_kind:
        raise OfficialProfileError("Official native preset kind does not match.")
    return raw
