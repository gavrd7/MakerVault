"""Strict native Prusa 2.9.7 printer topology and independent logical tools.

Source is an already owner-resolved immutable native printer INI. This
classification does not authorize printer transfer or multi-colour slicing.
Prusa MMU is a single-nozzle changer; XL has up to five independent hotends.
The INDX's up-to-eight passive tools need a separate, pinned vendor profile
and physical pickup/heater qualification; parsing eight tools does NOT enable it.
"""
import math
from .slicer_prusa_native_resolution import parse_prusa_profile


def prusa_machine_topology(printer_ini):
    parsed = parse_prusa_profile(printer_ini, "printer")
    raw = parsed.get("nozzle_diameter", "")
    try:
        nozzles = [float(x.strip()) for x in raw.split(",")]
    except (TypeError, ValueError):
        raise ValueError("Prusa printer has an invalid native nozzle vector.") from None
    if not 1 <= len(nozzles) <= 8 or any(
            not math.isfinite(x) or not .1 <= x <= 1.2 for x in nozzles):
        raise ValueError("Prusa printer has unsupported nozzle count or dimensions.")
    changer = parsed.get("single_extruder_multi_material", "0").strip().lower()
    if changer not in ("0", "1", "true", "false"):
        raise ValueError("Prusa printer material changer type is invalid.")
    same_nozzle = changer in ("1", "true")
    if same_nozzle and not 2 <= len(nozzles) <= 5:
        raise ValueError("Prusa MMU requires two to five logical material tools.")
    if parsed.get("binary_gcode", "0").strip().lower() not in ("", "0", "no", "false"):
        raise ValueError("Prusa binary G-code cannot enter text preview/worker.")
    return {
        "kind": "single_nozzle_changer" if same_nozzle else
                "unqualified_toolchanger" if len(nozzles) > 5 else
                "independent_tools" if len(nozzles) > 1 else "single_tool",
        "logical_tool_count": len(nozzles),
        "physical_nozzle_count": None if len(nozzles) > 5 else
                                 1 if same_nozzle else len(nozzles),
        "nozzle_diameters_mm": tuple(nozzles),
        "requires_new_toolchanger_qualification": len(nozzles) > 5,
    }


def validate_prusa_model_tool_order(printer_ini, tool_indices):
    """Require explicit one-based native per-object extruder metadata.

    Never infer Prusa T indices from a filament bay label, slot number or a
    zero-filled default; preserve user-specific native tool assignments.
    """
    topology = prusa_machine_topology(printer_ini)
    if not isinstance(tool_indices, (list, tuple)) or not 1 <= len(tool_indices) <= 12:
        raise ValueError("Prusa tool assignment requires one to twelve models.")
    seen = set()
    for tool in tool_indices:
        if type(tool) is not int or not 1 <= tool <= topology["logical_tool_count"]:
            raise ValueError("Model tool assignment is not a native Prusa extruder.")
        seen.add(tool)
    if len(seen) < 2:
        raise ValueError("Multi-material Prusa job requires two distinct native tools.")
    return {**topology, "selected_tools": tuple(sorted(seen))}
