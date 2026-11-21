"""Fail-closed Creality native CFS evidence gate for explicitly enabled presets.

Offline slicing validation only; nothing here approves printer transfer or
changes the printer, native presets, vendor macros or worker installation.
"""
import json


class CrealityCfsGateError(ValueError):
    """Safe fixed diagnostic reason; never echoes native printer scripts."""


def selected_creality_multicolor_capability(printer_profile):
    """Return true only for an explicit native machine-preset opt-in."""
    try:
        config = json.loads(printer_profile)
    except (TypeError, ValueError, UnicodeDecodeError) as exc:
        raise CrealityCfsGateError(
            "Selected Creality machine settings are invalid.") from exc
    if not isinstance(config, dict):
        raise CrealityCfsGateError("Selected Creality machine settings are invalid.")
    selected = config.get("multicolor_method")
    if selected is None:
        return False
    if type(selected) is bool:
        return selected
    if type(selected) is int and selected in (0, 1):
        return selected == 1
    if type(selected) is str and selected in ("0", "1"):
        return selected == "1"
    raise CrealityCfsGateError(
        "Selected Creality machine has an invalid multicolour capability.")


def audit_creality_multicolor_gcode(data):
    """Demand native balanced purge evidence with the enabled machine gate.

    Only called after a real approved offline worker slice for an explicitly
    opted-in machine preset. Tool selections alone are insufficient.
    """
    from .management.commands.diagnose_slicer_printer_profiles import (
        _creality_toolchange_macro_audit)
    if not isinstance(data, bytes) or not 0 < len(data) <= 64 * 1024 * 1024:
        raise CrealityCfsGateError("Native Creality G-code is not bounded.")
    audit = _creality_toolchange_macro_audit(data)
    if (not audit["flush_markers_balanced"]
            or not audit["flush_section_count_bounded"]
            or audit["unclassified_flush_g1_e_moves"]):
        raise CrealityCfsGateError(
            "Native Creality flush markers or extrusion sections are invalid.")
    if (not audit["completed_flush_sections"]
            or not audit["positive_extrusion_only_flush_moves"]
            or not audit["m8200_command_count"]
            or audit["tool_select_command_count"] < 2):
        raise CrealityCfsGateError(
            "Native Creality toolchange output has no verified multicolour purge.")
    if audit["extrusion_modes_observed_in_flush"] != ["relative"]:
        raise CrealityCfsGateError(
            "Native Creality flush extrusion must use an explicit relative mode.")
    return {
        "offline_native_purge_observed": True,
        "balanced_flush_sections": audit["completed_flush_sections"],
        "printer_submission_approved": False,
    }
