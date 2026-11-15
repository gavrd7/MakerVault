"""Validated, explicit Orca flushing matrix overrides for single-nozzle changers.

The directional matrix is ordered by *native tools*, not physical CFS/AMS
slots. Never invent a manufacturer purge macro or infer default volumes from
colour alone. Native profile settings remain the authority unless the user
overrides a precise transition. This is only an offline preflight utility.
"""
import json
import math

from .slicer_material_routing import MaterialRoutingError

MAX_FLUSH_MM3 = 20000
MAX_FLUSH_PAIRS = 240


def validate_flush_settings(value):
    if value is None:
        return None
    if not isinstance(value, dict) or set(value) != {
        "multiplier", "transitions", "prime_tower"
    }:
        raise MaterialRoutingError("Invalid flushing configuration.")
    multiplier = value["multiplier"]
    if multiplier is not None and (
            isinstance(multiplier, bool) or not isinstance(multiplier, (int, float))
            or not math.isfinite(multiplier) or not 0.1 <= multiplier <= 3):
        raise MaterialRoutingError("Flush multiplier must be between 0.1 and 3.")
    mode = value["prime_tower"]
    if mode not in ("native", "enabled", "disabled"):
        raise MaterialRoutingError("Invalid prime tower preference.")
    raw = value["transitions"]
    if not isinstance(raw, list) or len(raw) > MAX_FLUSH_PAIRS:
        raise MaterialRoutingError("Invalid flushing transition list.")
    result = []
    seen = set()
    for entry in raw:
        if not isinstance(entry, dict) or set(entry) != {
            "from_slot_id", "to_slot_id", "volume_mm3"
        }:
            raise MaterialRoutingError("Invalid flushing transition.")
        source, dest, amount = (entry[k] for k in
                                ("from_slot_id", "to_slot_id", "volume_mm3"))
        if (not isinstance(source, str) or not 1 <= len(source) <= 128
                or not isinstance(dest, str) or not 1 <= len(dest) <= 128
                or source == dest or (source, dest) in seen):
            raise MaterialRoutingError("Flushing transitions must be unique and directional.")
        if (isinstance(amount, bool) or not isinstance(amount, (int, float))
                or not math.isfinite(amount) or not 0 <= amount <= MAX_FLUSH_MM3):
            raise MaterialRoutingError("Flushing volume must be between 0 and 20,000 mm³.")
        seen.add((source, dest))
        result.append({"from_slot_id": source, "to_slot_id": dest,
                       "volume_mm3": round(float(amount), 3)})
    return {"multiplier": float(multiplier) if multiplier is not None else None,
            "transitions": result, "prime_tower": mode}


def apply_orca_flush_settings(process_bytes, settings, *, routes, tool_count, topology):
    """Return a derived native process JSON with explicit matrix/tool mapping.

    Missing volume entries are inherited from the verified native process
    matrix. If that matrix is absent, every off-diagonal transition must be
    explicitly configured; zero is NOT a safe default for colour changes.
    """
    approved = validate_flush_settings(settings)
    if approved is None:
        return process_bytes
    if topology != "single_nozzle_changer":
        raise MaterialRoutingError("CFS/AMS flushing volumes cannot be applied to independent toolheads.")
    if (isinstance(tool_count, bool) or not isinstance(tool_count, int)
            or not 2 <= tool_count <= 16):
        raise MaterialRoutingError("Invalid native tool palette for flushing.")
    try:
        process = json.loads(process_bytes)
    except (UnicodeDecodeError, ValueError, TypeError) as exc:
        raise MaterialRoutingError("Invalid native process profile for flushing.") from exc
    if not isinstance(process, dict):
        raise MaterialRoutingError("Invalid native process profile.")
    native = process.get("flush_volumes_matrix")
    if native is None:
        matrix = [None] * (tool_count * tool_count)
    else:
        if not isinstance(native, list) or len(native) != tool_count * tool_count:
            raise MaterialRoutingError("Native flushing matrix has an incompatible tool count.")
        matrix = []
        for val in native:
            try:
                if isinstance(val, bool):
                    raise ValueError("Boolean flushing value")
                num = float(val)
            except (ValueError, TypeError):
                raise MaterialRoutingError("Native flushing matrix contains invalid volumes.") from None
            if not math.isfinite(num) or not 0 <= num <= MAX_FLUSH_MM3:
                raise MaterialRoutingError("Native flushing matrix contains invalid volumes.")
            matrix.append(num)
    for index in range(tool_count):
        matrix[index * tool_count + index] = 0.0
    slot_to_tool = {}
    for route in routes:
        old = slot_to_tool.setdefault(route.slot_id, route.tool_index)
        if old != route.tool_index:
            raise MaterialRoutingError("A physical slot maps to conflicting native tools.")
        if not 0 <= route.tool_index < tool_count:
            raise MaterialRoutingError("A native tool exceeds the filament palette.")
    for change in approved["transitions"]:
        from_tool = slot_to_tool.get(change["from_slot_id"])
        to_tool = slot_to_tool.get(change["to_slot_id"])
        if from_tool is None or to_tool is None or from_tool == to_tool:
            raise MaterialRoutingError("A flush transition requires two distinct verified tool mappings.")
        matrix[from_tool * tool_count + to_tool] = change["volume_mm3"]
    if any(matrix[i * tool_count + j] is None
           for i in range(tool_count) for j in range(tool_count) if i != j):
        raise MaterialRoutingError(
            "Missing native flush volumes; configure every directional transition.")
    # Orca's JSON preset loader only accepts string elements in coFloats
    # arrays. Native Python JSON numbers can abort parsing before the
    # "from" profile metadata is read, producing misleading exit 251.
    process["flush_volumes_matrix"] = [format(value, ".3f").rstrip("0").rstrip(".")
                                       if value else "0" for value in matrix]
    if approved["multiplier"] is not None:
        # Orca 2.5 PrintConfig declares flush_multiplier as coFloats,
        # i.e. a vector (one value per nozzle), not a scalar coFloat.
        # The changer topology here has one nozzle and multiple filaments.
        process["flush_multiplier"] = [str(approved["multiplier"])]
    if approved["prime_tower"] != "native":
        process["enable_prime_tower"] = "1" if approved["prime_tower"] == "enabled" else "0"
    # No attempt to synthesize printer G-code: CFS/AMS unload, load, purge
    # location and tower type must remain from verified native presets.
    output = json.dumps(process, ensure_ascii=False, separators=(",", ":")).encode()
    if len(output) > 1024 * 1024:
        raise MaterialRoutingError("Native flushing settings exceed the profile size limit.")
    return output
