"""Owner-scoped, fail-closed Prusa INI resolution for *candidate* slicing profiles.

Upstream vendor sections are flattened at explicit Prusa import time. At job
admission we independently reread their immutable private asset, verify its
stored digest and refuse unresolved or executable native directives. This
module must never modify the three released JSON-based slicer engines.
"""
import hashlib
import re

from .slicer_profiles import SlicerProfileError

MAX_BYTES = 1024 * 1024
KEY = re.compile(r"[A-Za-z_][A-Za-z0-9_]*\Z")
REQUIRED = {
    "printer": {"nozzle_diameter", "bed_shape"},
    "filament": {"filament_diameter"},
    "process": {"layer_height"},
}
BLOCKED = {
    "post_process", "post_process_scripts", "post_processing",
    "post_processing_scripts", "config_include", "include", "include_file",
    "script",
}


def resolved_prusa_profile(profile) -> bytes:
    if profile.engine != "prusaslicer" or profile.kind not in REQUIRED:
        raise SlicerProfileError("Prusa profile resolution requires a matching engine and kind.")
    asset = profile.file_asset
    if not asset or not asset.file or asset.owner_id != profile.owner_id:
        raise SlicerProfileError("Prusa native profile source is not owned or available.")
    try:
        with asset.file.storage.open(asset.file.name, "rb") as stream:
            raw = stream.read(MAX_BYTES + 1)
    except (OSError, ValueError):
        raise SlicerProfileError("Prusa native profile content is unavailable.") from None
    if not 0 < len(raw) <= MAX_BYTES or hashlib.sha256(raw).hexdigest() != profile.content_sha256:
        raise SlicerProfileError("Prusa native profile changed since import.")
    parse_prusa_profile(raw, profile.kind)
    return raw


def parse_prusa_profile(raw, kind):
    if kind not in REQUIRED or not isinstance(raw, bytes) or not 0 < len(raw) <= MAX_BYTES:
        raise SlicerProfileError("Invalid Prusa native profile.")
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise SlicerProfileError("Prusa native profile must be UTF-8 text.") from None
    if any((ord(ch) < 32 and ch not in "\n\r\t") or ord(ch) == 127 for ch in text):
        raise SlicerProfileError("Prusa native profile has unsafe control bytes.")
    settings = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith(("#", ";")):
            continue
        if line.startswith("[") or "=" not in line:
            raise SlicerProfileError("Prusa profile must be a flattened native INI.")
        key, _, val = line.partition("=")
        key, val = key.strip(), val.strip()
        if (not KEY.fullmatch(key) or len(val) > 16384
                or key in settings or len(settings) >= 400):
            raise SlicerProfileError("Prusa native profile contains invalid settings.")
        if key == "inherits":
            raise SlicerProfileError("Prusa preset inheritance is unresolved.")
        if key in BLOCKED and (key in {"include", "config_include", "include_file", "script"}
                               or val):
            raise SlicerProfileError("Prusa native executable directives are unsupported.")
        if key == "binary_gcode" and val.lower() not in {"", "0", "false", "no"}:
            raise SlicerProfileError("Only plain-text Prusa G-code is supported.")
        settings[key] = val
    if not REQUIRED[kind].issubset(settings):
        raise SlicerProfileError("Prusa native profile is missing required settings.")
    if kind == "printer" and settings.get("printer_technology", "FFF") != "FFF":
        raise SlicerProfileError("Only Prusa FFF printer profiles are supported.")
    return settings
