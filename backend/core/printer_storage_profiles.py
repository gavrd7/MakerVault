"""Printer storage strategies for setup diagnostics and adapter routing.

A path is only a filesystem location for adapters that send paths explicitly.
API-managed adapters must use the manufacturer's file API, never infer a
filesystem path from a ping or the printer marketing model.
"""
import re

# Storage capabilities describe protocols, NOT general printer support.
# Entries marked unavailable are deliberate until the target firmware's
# upload and start contract is verified.
PROFILES = (
    ("creality_k1", r"\bK1(?:C| SE| MAX)?\b", "creality_local", "native_path", "/usr/data/printer_data/gcodes/", "model_known"),
    ("creality_k2", r"\bK2(?:\b|\s+(?:PLUS|PRO|SE))", "creality_local", "native_path", "/mnt/UDISK/printer_data/gcodes/", "model_known"),
    ("creality_hi", r"\bCREALITY\s+HI\b|\bHI\s+COMBO\b", "creality_local", "firmware_probe_required", None, "unverified"),
    ("creality_sparkx", r"\bSPARKX\s*I[78]\b", "creality_local", "firmware_probe_required", None, "unverified"),
    ("creality_ender_v3", r"\bENDER[- ]?3\s+V3(?:\s+(?:KE|SE|PLUS))?\b", "creality_local", "firmware_probe_required", None, "unverified"),
    ("bambu_x1_p1_a1", r"\b(?:X1(?:C|E| CARBON)?|P1[PS]|A1(?: MINI)?)\b", "bambu_local", "ftps_model_profile", None, "protocol_documented"),
    ("bambu_new", r"\b(?:P2S|H2[DSC]|X2D)\b", "bambu_local", "ftps_model_profile", None, "protocol_documented"),
    ("prusa_ht90", r"\bHT90\b", "prusa", "requires_vendor_adapter", None, "unverified"),
    ("prusa", r"\b(?:PRUSA|MK[234](?:\.[059])?(?:S|\+)?|CORE ONE|XL|MINI)\b", "prusa", "prusalink_storage_api", None, "api_managed"),
    ("anycubic_new", r"\b(?:KOBRA\s*(?:2|3|4|S1|X))\b", "anycubic", "anycubic_upload_api", None, "firmware_dependent"),
    ("flashforge", r"\b(?:FLASHFORGE|ADVENTURER|CREATOR|GUIDER)\b", "flashforge", "flashforge_model_api", None, "firmware_dependent"),
    ("snapmaker_u1", r"\b(?:SNAPMAKER\s*)?U1\b", "snapmaker", "moonraker_storage_api", None, "api_managed"),
)


# Reference routes from inspected slicer implementations. These are hints only;
# MakerVault does not yet enable Bambu upload/start via this catalogue.
BAMBU_REFERENCE_ROUTES = (
    (r"\b(?:X1(?:C|E| CARBON)?|P1[PS]|A1 MINI)\b", "/cache/", "gcode_file"),
    (r"\bA1\b(?!\s*MINI)", "/", "project_file"),
    (r"\bP2S\b", "/cache/", "project_file"),
    (r"\bH2[DSC]\b", "/", "project_file"),
)


def bambu_reference_route(model):
    """Slicer-documented route; not a verified upload capability."""
    value = str(model or "").upper()
    if re.search(r"\bX2D\b", value):
        return None  # Requires newer model-specific helper, not legacy FTPS.
    for pattern, remote_dir, start_command in BAMBU_REFERENCE_ROUTES:
        if re.search(pattern, value):
            return {"remote_directory_hint": remote_dir, "start_command_hint": start_command,
                    "usable_for_upload": False}
    return None


def storage_profile(adapter, model):
    """Return an explicitly supported strategy, not a speculative path."""
    if adapter == "moonraker":
        return {"key": "generic_moonraker", "strategy": "moonraker_storage_api", "path": None, "confidence": "api_managed"}
    if adapter == "octoprint":
        return {"key": "generic_octoprint", "strategy": "octoprint_storage_api", "path": None, "confidence": "api_managed"}
    text = str(model or "").upper().strip()
    for key, pattern, match_adapter, strategy, path, confidence in PROFILES:
        if adapter == match_adapter and re.search(pattern, text):
            result = {"key": key, "strategy": strategy, "path": path, "confidence": confidence}
            if adapter == "bambu_local":
                result["reference_route"] = bambu_reference_route(text)
            return result
    return {"key": "unknown", "strategy": "unsupported_until_verified", "path": None, "confidence": "unknown"}
