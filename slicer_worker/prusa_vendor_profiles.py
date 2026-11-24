"""Strict, offline PrusaSlicer vendor INI preset extraction and inheritance.

Prusa's official vendor bundles (resources/profiles/PrusaResearch.ini) use
[print:...], [filament:...], and [printer:...] sections. Those are *not* three
ready-to-load INI files. Resolve exactly one requested section per kind, using
only the same checked bundle and matching namespace, then export flat CLI INI.

No URL, profile path or arbitrary config data can be executed by this module.
The caller owns and verifies the exact upstream source/version bytes.
"""
from __future__ import annotations

import hashlib
import re

MAX_BUNDLE_BYTES = 4 * 1024 * 1024
MAX_FLAT_BYTES = 1024 * 1024
MAX_SECTIONS = 10000
MAX_KEYS = 400
MAX_DEPTH = 16
KINDS = frozenset({"print", "filament", "printer"})
NAME = re.compile(r"[A-Za-z0-9*][^\[\]\r\n]{0,199}\Z")
KEY = re.compile(r"[A-Za-z_][A-Za-z0-9_]*\Z")
# Prusa's CLI does not need dynamic post-processing; this is executable.
SCRIPT_KEYS = frozenset({"post_process", "post_process_scripts", "post_processing",
                         "post_processing_scripts"})
CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


class PrusaPresetError(ValueError):
    """Fixed-message validation refusal: do not expose private INI contents."""


def _decode(raw: bytes) -> str:
    if not isinstance(raw, bytes) or not 0 < len(raw) <= MAX_BUNDLE_BYTES:
        raise PrusaPresetError("Prusa vendor bundle size is invalid.")
    try:
        body = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise PrusaPresetError("Prusa vendor bundle must be UTF-8.") from None
    if CONTROL.search(body):
        raise PrusaPresetError("Prusa vendor bundle contains unsafe control bytes.")
    return body


def _checked_setting(key: str, value: str) -> None:
    if not KEY.fullmatch(key) or len(value) > 16384:
        raise PrusaPresetError("Prusa vendor bundle has an invalid setting.")
    if key.lower() in SCRIPT_KEYS and value.strip():
        raise PrusaPresetError("Post-processing scripts are forbidden.")
    # Externally loaded configurations and scripts are not part of a self-
    # contained preset; treat references as inert only when explicitly known.
    if key.lower() in {"config_include", "include", "include_file", "script"}:
        raise PrusaPresetError("External Prusa profile directives are forbidden.")


def parse_prusa_vendor_bundle(raw: bytes) -> dict:
    """Parse literal sections, rejecting duplicates rather than silent override.

    Values are kept verbatim: Python's ConfigParser interprets '%' and ':'
    differently from PrusaSlicer's native INI format.
    """
    text = _decode(raw)
    sections: dict[str, dict[str, str]] = {}
    current: dict | None = None
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith(("#", ";")):
            continue
        if stripped.startswith("["):
            if not stripped.endswith("]") or stripped.count("[") != 1:
                raise PrusaPresetError("Invalid Prusa vendor preset section.")
            name = stripped[1:-1]
            if not NAME.fullmatch(name) or name in sections:
                raise PrusaPresetError("Duplicate or invalid Prusa preset section.")
            if len(sections) >= MAX_SECTIONS:
                raise PrusaPresetError("Prusa vendor preset count exceeds limit.")
            current = {}
            sections[name] = current
            continue
        if current is None or "=" not in line:
            raise PrusaPresetError("Invalid Prusa vendor preset setting.")
        key, _, value = line.partition("=")
        key, value = key.strip(), value.strip()
        _checked_setting(key, value)
        if len(current) >= MAX_KEYS or key in current:
            raise PrusaPresetError("Duplicate or excessive Prusa preset setting.")
        current[key] = value
    if not sections:
        raise PrusaPresetError("Prusa vendor bundle contains no presets.")
    return sections


def flatten_prusa_vendor_preset(
    raw: bytes, *, kind: str, name: str, expected_sha256: str | None = None
) -> bytes:
    """Return strictly one fully flattened printer/filament/print CLI INI.

    No fallback across vendors, versions, preset kinds or missing parents.
    The supplied digest can bind the exact vetted upstream vendor bundle.
    """
    if kind not in KINDS or not isinstance(name, str) or not NAME.fullmatch(name):
        raise PrusaPresetError("Invalid Prusa preset selection.")
    if expected_sha256 is not None and (
        not isinstance(expected_sha256, str)
        or not re.fullmatch(r"[a-f0-9]{64}", expected_sha256)
        or hashlib.sha256(raw).hexdigest() != expected_sha256
    ):
        raise PrusaPresetError("Prusa vendor source checksum mismatch.")
    sections = parse_prusa_vendor_bundle(raw)
    cache: dict[str, dict[str, str]] = {}

    def resolve(label: str, depth: int, active=frozenset()) -> dict[str, str]:
        section = kind + ":" + label
        if depth >= MAX_DEPTH or section in active:
            raise PrusaPresetError("Prusa preset inheritance is cyclic or too deep.")
        if section in cache:
            return dict(cache[section])
        data = sections.get(section)
        if data is None:
            raise PrusaPresetError("Prusa native preset parent is missing.")
        merged = {}
        parents = data.get("inherits", "").strip()
        if parents:
            # Native Prusa bundles support multiple parents separated by ';'.
            # Later parents override earlier parents; the selected child wins.
            names = [part.strip() for part in parents.split(";")]
            if len(names) > 12 or any(not NAME.fullmatch(parent) for parent in names):
                raise PrusaPresetError("Invalid Prusa preset parent.")
            for parent in names:
                merged.update(resolve(parent, depth + 1, active | {section}))
        merged.update({key: value for key, value in data.items()
                       if key != "inherits"})
        if len(merged) > MAX_KEYS:
            raise PrusaPresetError("Prusa preset has too many resolved settings.")
        cache[section] = dict(merged)
        return merged

    settings = resolve(name, 0)
    if not settings:
        raise PrusaPresetError("Prusa preset has no usable settings.")
    if kind == "printer" and settings.get("printer_technology", "FFF") != "FFF":
        raise PrusaPresetError("Only Prusa FFF printer presets are supported.")
    for key, value in settings.items():
        _checked_setting(key, value)
    # Flat INI: native --load consumes these settings, not section selectors.
    output = "".join(f"{key} = {value}\n" for key, value in sorted(settings.items()))
    result = output.encode("utf-8")
    if not 0 < len(result) <= MAX_FLAT_BYTES:
        raise PrusaPresetError("Resolved Prusa native preset exceeds its limit.")
    return result


# Prusa's --load accepts flat native settings. An upstream vendor catalogue
# [printer:NAME] section is *not* executable without inheritance resolution.
REQUIRED_FLAT_KEYS = {
    "printer": frozenset({"nozzle_diameter", "bed_shape"}),
    "filament": frozenset({"filament_diameter"}),
    "print": frozenset({"layer_height"}),
}


def validate_flat_prusa_preset(raw: bytes, *, kind: str) -> dict[str, str]:
    """Validate one resolved Prusa CLI preset, never executing external input."""
    if kind not in KINDS:
        raise PrusaPresetError("Unsupported Prusa native preset kind.")
    if not isinstance(raw, bytes) or not 0 < len(raw) <= MAX_FLAT_BYTES:
        raise PrusaPresetError("Prusa flat preset size is invalid.")
    text = _decode(raw)
    settings: dict[str, str] = {}
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith(("#", ";")):
            continue
        if stripped.startswith("[") or "=" not in line:
            raise PrusaPresetError("Prusa CLI requires a flattened native preset.")
        key, _, value = line.partition("=")
        key, value = key.strip(), value.strip()
        _checked_setting(key, value)
        if key in settings or len(settings) >= MAX_KEYS:
            raise PrusaPresetError("Duplicate or excessive Prusa native preset setting.")
        if key == "inherits":
            raise PrusaPresetError("Prusa preset inheritance must be resolved first.")
        if key == "binary_gcode" and value.strip().lower() not in {"", "0", "false", "no"}:
            raise PrusaPresetError("Only text Prusa G-code is supported.")
        settings[key] = value
    if not REQUIRED_FLAT_KEYS[kind].issubset(settings):
        raise PrusaPresetError("Prusa CLI preset lacks required native settings.")
    if kind == "printer" and settings.get("printer_technology", "FFF") != "FFF":
        raise PrusaPresetError("Only Prusa FFF printer presets are supported.")
    return settings
