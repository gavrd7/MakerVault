"""Reviewed, bounded PrusaSlicer vendor-bundle printer-model discovery.

The extracted model section is artwork metadata only. It is never an
executable printer preset and cannot be used to approve a slicing worker.
"""
from configparser import ConfigParser, Error as ConfigError
from functools import lru_cache

import requests

from .slicer_official_profiles import OfficialProfileError

ENGINE = "prusaslicer"
ENGINE_VERSION = "2.9.6"
SOURCE = "prusa3d/PrusaSlicer"
REF = "version_2.9.6"
BASE = f"https://raw.githubusercontent.com/{SOURCE}/{REF}/resources/profiles"
VENDORS = ("PrusaResearch",)
MAX_INI = 3 * 1024 * 1024


@lru_cache(maxsize=4)
def _sections(vendor="PrusaResearch"):
    if vendor not in VENDORS:
        raise OfficialProfileError("Prusa vendor is not in the approved catalogue.")
    try:
        result = requests.get(f"{BASE}/{vendor}.ini", timeout=(3, 15),
                              stream=True, allow_redirects=False,
                              headers={"User-Agent": "MakerVault-PrusaModelBrowser/1"})
        try:
            if result.status_code != 200:
                raise OfficialProfileError("Official Prusa vendor bundle is unavailable.")
            declared = result.headers.get("Content-Length")
            if declared and int(declared) > MAX_INI:
                raise OfficialProfileError("Prusa vendor bundle exceeds its limit.")
            chunks = bytearray()
            for chunk in result.iter_content(65536):
                chunks.extend(chunk)
                if len(chunks) > MAX_INI:
                    raise OfficialProfileError("Prusa vendor bundle exceeds its limit.")
        finally:
            result.close()
        data = bytes(chunks).decode("utf-8-sig")
        parser = ConfigParser(strict=False, interpolation=None, delimiters=("=",))
        parser.optionxform = str.lower
        parser.read_string(data)
    except (requests.RequestException, UnicodeDecodeError, ConfigError, ValueError) as exc:
        if isinstance(exc, OfficialProfileError):
            raise
        raise OfficialProfileError("Could not inspect the official Prusa vendor bundle.") from exc
    found = {}
    for section in parser.sections():
        if not section.startswith("printer_model:"):
            continue
        values = dict(parser.items(section))
        name = values.get("name") or section.partition(":")[2]
        if not 1 <= len(name) <= 200:
            continue
        if name in found:
            raise OfficialProfileError("Ambiguous Prusa printer model names in vendor bundle.")
        # Keep the original registered name and only the exact native
        # bed-model metadata; user-supplied arbitrary filesystem paths cannot
        # reach the asset downloader, which independently validates them.
        found[name] = (section, {
            key: value for key, value in values.items()
            if key in ("name", "bed_model", "bed_texture")
        })
        if len(found) > 500:
            raise OfficialProfileError("Prusa vendor model catalogue is too large.")
    return found


def available_prusa_vendors():
    return [{"id": "PrusaResearch", "label": "Prusa Research"}]


def official_catalogue_models(vendor="PrusaResearch"):
    return sorted(_sections(vendor), key=str.casefold)


def search_prusa_profiles(query, kind, vendor="PrusaResearch", printer_model=None):
    if kind != "printer":
        raise OfficialProfileError("Prusa artwork discovery currently supports printer-model metadata only.")
    if not isinstance(query, str) or not 2 <= len(query.strip()) <= 80:
        raise OfficialProfileError("Enter at least two search characters.")
    needle = query.strip().casefold()
    models = _sections(vendor)
    matches = [name for name in models if needle in name.casefold()]
    if printer_model:
        matches = [name for name in matches if name == printer_model]
    return {
        "engine": ENGINE, "engine_version": ENGINE_VERSION,
        "vendor": vendor, "kind": kind, "source": SOURCE, "ref": REF,
        "profiles": [{"name": name, "sub_path": vendor + ".ini"} for name in matches[:40]],
        "total_matches": len(matches), "import_status": "candidate_only",
        "model_artwork_only": True,
    }


def fetch_prusa_model(kind, name, subpath, vendor="PrusaResearch"):
    if kind != "printer" or subpath != vendor + ".ini":
        raise OfficialProfileError("Prusa model is not in the approved vendor bundle.")
    entry = _sections(vendor).get(name)
    if not entry:
        raise OfficialProfileError("Prusa printer model is not in the official vendor bundle.")
    section, values = entry
    # Extract just one printer-model section, not the multi-megabyte
    # settings bundle or arbitrary executable print/process configuration.
    lines = ["[" + section + "]"]
    lines.extend(f"{key} = {value}" for key, value in values.items()
                 if "\n" not in value and "\r" not in value)
    return ("\n".join(lines) + "\n").encode("utf-8")
