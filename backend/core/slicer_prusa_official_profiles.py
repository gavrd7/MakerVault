"""Reviewed, bounded PrusaSlicer vendor-bundle printer-model discovery.

The extracted model section is artwork metadata only. It is never an
executable printer preset and cannot be used to approve a slicing worker.
"""
from configparser import ConfigParser, Error as ConfigError
from functools import lru_cache
import re

import requests

from .slicer_official_profiles import OfficialProfileError

ENGINE = "prusaslicer"
ENGINE_VERSION = "2.9.7"
SOURCE = "prusa3d/PrusaSlicer"
REF = "version_2.9.7"
# Immutable commit backing the reviewed 2.9.7 annotated release tag.
SOURCE_COMMIT = "450d70dd81c9b8990bc6bc8e690e31f82ddceb11"
BASE = f"https://raw.githubusercontent.com/{SOURCE}/{SOURCE_COMMIT}/resources/profiles"
VENDORS = ("PrusaResearch",)
MAX_INI = 3 * 1024 * 1024


@lru_cache(maxsize=4)
def _native_sections(vendor="PrusaResearch"):
    """Read exactly one pinned upstream vendor INI into bounded literal sections."""
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
        if any(ord(char) == 0 for char in data):
            raise OfficialProfileError("Prusa vendor bundle is not plain text.")
        parser = ConfigParser(strict=True, interpolation=None, delimiters=("=",))
        parser.optionxform = str
        parser.read_string(data)
        if not 0 < len(parser.sections()) <= 10000:
            raise OfficialProfileError("Official Prusa vendor preset count is invalid.")
        return {section: dict(parser.items(section)) for section in parser.sections()}
    except (requests.RequestException, UnicodeDecodeError, ConfigError, ValueError) as exc:
        if isinstance(exc, OfficialProfileError):
            raise
        raise OfficialProfileError("Could not inspect the official Prusa vendor bundle.") from exc


@lru_cache(maxsize=4)
def _sections(vendor="PrusaResearch"):
    """Printer artwork metadata, separate from executable printer profiles."""
    found = {}
    for section, values in _native_sections(vendor).items():
        if not section.startswith("printer_model:"):
            continue
        name = values.get("name") or section.partition(":")[2]
        if not 1 <= len(name) <= 200:
            continue
        if name in found:
            raise OfficialProfileError("Ambiguous Prusa printer model names in vendor bundle.")
        found[name] = (section, {
            key: value for key, value in values.items()
            if key in ("name", "bed_model", "bed_texture")
        })
        if len(found) > 500:
            raise OfficialProfileError("Prusa vendor model catalogue is too large.")
    return found


_PRUSA_KINDS = {"printer": "printer", "filament": "filament", "process": "print"}
_NATIVE_KEY = re.compile(r"[A-Za-z_][A-Za-z0-9_]*\Z")
_MAX_NATIVE_SETTINGS = 400


def _flatten_native_profile(kind, name, vendor):
    """Flatten same-vendor/same-kind inheritance; never load external paths."""
    prefix = _PRUSA_KINDS.get(kind)
    if not prefix or not isinstance(name, str) or not 1 <= len(name) <= 200:
        raise OfficialProfileError("Unsupported Prusa native preset selection.")
    sections = _native_sections(vendor)
    resolved = {}

    def resolve(selected, depth=0, active=frozenset()):
        section = prefix + ":" + selected
        if depth >= 16 or section in active:
            raise OfficialProfileError("Prusa native preset inheritance is circular or too deep.")
        if section in resolved:
            return dict(resolved[section])
        fields = sections.get(section)
        if not isinstance(fields, dict):
            raise OfficialProfileError("Prusa native preset parent is missing.")
        inherited = {}
        parents = fields.get("inherits", "").strip()
        if parents:
            names = [parent.strip() for parent in parents.split(";")]
            if (len(names) > 12 or any(not 1 <= len(parent) <= 200
                                       or "[" in parent or "]" in parent for parent in names)):
                raise OfficialProfileError("Invalid Prusa native preset inheritance.")
            for parent in names:
                inherited.update(resolve(parent, depth + 1, active | {section}))
        for key, value in fields.items():
            if key == "inherits":
                continue
            if (not _NATIVE_KEY.fullmatch(key) or not isinstance(value, str)
                    or len(value) > 16384 or any(ord(char) == 0 for char in value)):
                raise OfficialProfileError("Invalid official Prusa native setting.")
            if key.lower() in {"post_process", "post_process_scripts",
                               "post_processing", "post_processing_scripts"} and value.strip():
                raise OfficialProfileError("Prusa native post-processing scripts are forbidden.")
            if key.lower() in {"config_include", "include", "include_file", "script"}:
                raise OfficialProfileError("External Prusa preset references are unsupported.")
            inherited[key] = value
        if len(inherited) > _MAX_NATIVE_SETTINGS:
            raise OfficialProfileError("Prusa native preset exceeds its complexity limit.")
        resolved[section] = dict(inherited)
        return inherited

    settings = resolve(name)
    required = {
        "printer": {"nozzle_diameter", "bed_shape"},
        "filament": {"filament_diameter"},
        "process": {"layer_height"},
    }[kind]
    if not required.issubset(settings):
        raise OfficialProfileError("Official Prusa native preset is incomplete.")
    if kind == "printer" and settings.get("printer_technology", "FFF") != "FFF":
        raise OfficialProfileError("Only Prusa FFF printer presets are supported.")
    # Official MK4, MK4S and CORE One FFF presets often default to BG-code.
    # MakerVault's bounded G-code preview/auditor needs text G-code instead.
    # This import-only conversion follows validated, immutable upstream
    # inheritance. Do not alter stored originals or arbitrary user INI.
    binary_gcode = settings.get("binary_gcode", "0").strip().lower()
    if binary_gcode in {"1", "true", "yes"}:
        settings["binary_gcode"] = "0"
    elif binary_gcode not in {"", "0", "false", "no"}:
        raise OfficialProfileError("Unsupported Prusa binary G-code preference.")
    flattened = "".join(f"{key} = {value}\n" for key, value in sorted(settings.items()))
    raw = flattened.encode("utf-8")
    if not 0 < len(raw) <= 1024 * 1024:
        raise OfficialProfileError("Official Prusa resolved preset exceeds its limit.")
    return raw


def fetch_prusa_profile(kind, name, subpath, vendor="PrusaResearch"):
    """Import one verified-source, fully flattened *candidate* CLI preset."""
    if vendor not in VENDORS or subpath != vendor + ".ini":
        raise OfficialProfileError("Prusa source selection does not match the approved vendor.")
    return _flatten_native_profile(kind, name, vendor)


def available_prusa_vendors():
    return [{"id": "PrusaResearch", "label": "Prusa Research"}]


def official_catalogue_models(vendor="PrusaResearch"):
    return sorted(_sections(vendor), key=str.casefold)


def search_prusa_profiles(query, kind, vendor="PrusaResearch", printer_model=None, *, offset=0):
    """Discover *native* Prusa printer, filament and process candidates."""
    prefix = _PRUSA_KINDS.get(kind)
    if not prefix:
        raise OfficialProfileError("Choose a Prusa printer, filament or process preset.")
    if not isinstance(query, str) or len(query.strip()) > 80:
        raise OfficialProfileError("Search terms must be 80 characters or fewer.")
    if printer_model is not None and (
            not isinstance(printer_model, str) or len(printer_model) > 200):
        raise OfficialProfileError("Invalid Prusa native printer-model filter.")
    needle = query.strip().casefold()
    sections = _native_sections(vendor)
    matches = []
    for section in sections:
        if not section.startswith(prefix + ":"):
            continue
        name = section[len(prefix) + 1:]
        # Internal symbolic defaults are resolved through inheritance, never
        # presented to users as complete ready-to-select profiles.
        if not 1 <= len(name) <= 200 or name.startswith("*"):
            continue
        if needle not in name.casefold():
            continue
        if printer_model and kind == "printer" and printer_model.casefold() not in name.casefold():
            continue
        matches.append(name)
    matches.sort(key=str.casefold)
    return {
        "engine": ENGINE, "engine_version": ENGINE_VERSION,
        "vendor": vendor, "kind": kind, "source": SOURCE, "ref": REF,
        "profiles": [{"name": name, "sub_path": vendor + ".ini"} for name in matches[offset:offset + 40]],
        "total_matches": len(matches), "import_status": "candidate_only",
        "model_artwork_only": False,
        "compatibility_not_verified": True,
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
