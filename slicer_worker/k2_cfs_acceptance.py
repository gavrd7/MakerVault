"""K2-specific *offline* native-profile acceptance; never approves hardware.

This is a diagnostic profile identity + configuration check for a pinned
Creality K2 Combo CFS test fixture, not a general manufacturer capability
classifier. Actual installed CFS, firmware, live slot identity, and printer
start commands must be checked separately before any physical test.
"""
import json
import math

from .runner import WorkerError


def k2_offline_profile_evidence(printer_bytes, process_bytes):
    try:
        printer = json.loads(printer_bytes)
        process = json.loads(process_bytes)
    except (TypeError, ValueError, UnicodeDecodeError) as exc:
        raise WorkerError("The K2 acceptance requires valid resolved native JSON.") from exc
    if not isinstance(printer, dict) or not isinstance(process, dict):
        raise WorkerError("The K2 native profiles must contain JSON objects.")
    name = printer.get("name")
    if name != "Creality K2 0.4 nozzle":
        raise WorkerError("The K2 acceptance fixture needs the exact K2 machine profile.")
    required = {
        "single_extruder_multi_material": "1",
        "manual_filament_change": "0",
        "purge_in_prime_tower": "1",
    }
    for key, expected in required.items():
        if printer.get(key) != expected:
            raise WorkerError("The K2 native machine profile lacks a required CFS changeover setting.")
    macro = printer.get("change_filament_gcode")
    if not isinstance(macro, str) or not macro.strip() or len(macro) > 12000:
        raise WorkerError("The K2 native filament-change macro is missing or invalid.")
    if process.get("enable_prime_tower") != "1":
        raise WorkerError("The K2 acceptance fixture requires native prime tower enabled.")
    matrix = process.get("flush_volumes_matrix")
    if not isinstance(matrix, list) or len(matrix) != 4:
        raise WorkerError("The two-tool K2 flushing matrix must be exactly 2 by 2.")
    checked = []
    for value in matrix:
        if isinstance(value, bool) or not isinstance(value, (str, int, float)):
            raise WorkerError("The K2 flushing matrix must have bounded numeric values.")
        try:
            number = float(value)
        except ValueError:
            raise WorkerError("The K2 flushing matrix contains invalid values.") from None
        if not math.isfinite(number) or not 0 <= number <= 20000:
            raise WorkerError("The K2 flushing matrix contains invalid values.")
        checked.append(number)
    if checked[0] != 0 or checked[3] != 0 or min(checked[1], checked[2]) <= 0:
        raise WorkerError("The K2 fixture requires nonzero directional flushing.")
    return {
        "k2_native_profile_checked": True,
        "single_nozzle_changer_profile": True,
        "native_changeover_macro_present": True,
        "prime_tower_requested": True,
        "directional_flush_mm3": [checked[1], checked[2]],
        "physical_cfs_approved": False,
    }
