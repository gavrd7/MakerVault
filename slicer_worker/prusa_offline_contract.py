"""Independent worker-side MMU offline admission checks (not printer dispatch).

Unlike the backend's owner-scoped compiler, this module trusts no request
metadata. The worker re-parses the exact bytes it will feed to Prusa 2.9.7.
"""
import math

from .prusa_material_validation import validate_prusa_material_candidate, _qualified_topology
from .prusa_vendor_profiles import validate_flat_prusa_preset, PrusaPresetError
from .runner import WorkerError


def validate_prusa_offline_mmu_inputs(*, project, printer, filament, process,
                                      tools, tower):
    count, same_nozzle = _qualified_topology(printer)
    if not same_nozzle or not 2 <= count <= 5:
        raise WorkerError("Prusa offline MMU requires an explicit changer machine.")
    if (not isinstance(tools, list) or not 2 <= len(tools) <= 5
            or any(type(t) is not int or not 1 <= t <= count for t in tools)
            or len(set(tools)) < 2):
        raise WorkerError("Prusa offline MMU model tool selection is invalid.")
    if (not isinstance(tower, list) or len(tower) != 5 or
            any(type(v) not in (int, float) or not math.isfinite(v) for v in tower)):
        raise WorkerError("Prusa offline MMU wipe tower specification is invalid.")
    try:
        filament_settings = validate_flat_prusa_preset(filament, kind="filament")
        process_settings = validate_flat_prusa_preset(process, kind="print")
    except PrusaPresetError:
        raise WorkerError("Prusa offline MMU native profiles are invalid.") from None
    if (process_settings.get("wipe_tower") != "1" or
            process_settings.get("wipe_into_infill") != "0" or
            process_settings.get("wipe_into_objects") != "0"):
        raise WorkerError("Prusa offline MMU requires isolated native wipe tower purging.")
    for key in ("temperature", "first_layer_temperature"):
        raw = filament_settings.get(key, "").split(",")
        if (len(raw) != count or any(
                not value.isascii() or not value.isdecimal()
                or not 0 <= int(value) <= 350 for value in raw)):
            raise WorkerError("Prusa offline MMU native temperature vector is invalid.")
    # Prusa's logical material transition matrix is row-major, tool->tool.
    parts = process_settings.get("wiping_volumes_matrix", "").split(",")
    if len(parts) != count * count:
        raise WorkerError("Prusa offline MMU purge matrix dimensions are invalid.")
    for index, value in enumerate(parts):
        try:
            number = float(value)
        except ValueError:
            raise WorkerError("Prusa offline MMU purge volume is invalid.") from None
        diagonal = index // count == index % count
        if (not math.isfinite(number) or number < 0 or number > 1000
                or (diagonal and number != 0)
                or (not diagonal and number < 1)):
            raise WorkerError("Prusa offline MMU transition volume is invalid.")
    receipt = validate_prusa_material_candidate(
        project, printer_ini=printer, tools=tools, tower=tower)
    if (receipt["objects"] != len(tools) or not receipt["wipe_tower"]
            or set(receipt["tools"]) != set(tools)):
        raise WorkerError("Prusa offline MMU project/tool assignment mismatch.")
    return {"tools": tuple(tools), "tool_count": count,
            "wipe_tower": True, "offline_only": True}
