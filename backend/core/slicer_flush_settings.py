"""Engine-neutral directional flushing request validation.

The directional matrix is ordered by *native tools*, not physical CFS/AMS
slots. Never invent a manufacturer purge macro or infer default volumes from
colour alone. Native profile settings remain the authority unless the user
overrides a precise transition. This is only an offline preflight utility.
"""
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
    """Compatibility entrypoint: delegate native serialization to Orca adapter.

    The common schema and existing callers are unchanged. Printer topology
    validation and all native value translation live in the engine adapter.
    """
    from .slicer_flush_adapters import apply_orca_native_flush
    return apply_orca_native_flush(
        process_bytes, settings, routes=routes,
        tool_count=tool_count, topology=topology)
