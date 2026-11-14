"""Provider-neutral material routing for slicer drafts.

An observed CFS/AMS bay is not a slicer extruder. Physical slots and native
tool indices have separate identities; only explicit verified bindings may
join them. This module never emits firmware commands.
"""
from dataclasses import dataclass


class MaterialRoutingError(ValueError):
    pass


TOPOLOGIES = frozenset({"single_nozzle_changer", "independent_toolheads"})


@dataclass(frozen=True)
class MaterialRoute:
    instance_id: str
    printer_id: str
    slot_id: str
    slot_index: int
    tool_index: int


def plan_material_routes(objects, *, printer_id, topology, tool_bindings):
    """Validate an explicit physical-slot -> native-tool map.

    tool_bindings maps a physical slot ID to a zero-based, non-negative native
    extruder/tool index. Its ordering must be verified against the selected
    engine's native filament palette and the specific printer profile.
    Nothing about a physical slot's index implies an Orca extruder index.
    """
    if topology not in TOPOLOGIES:
        raise MaterialRoutingError("Unsupported printer material topology.")
    if not isinstance(tool_bindings, dict):
        raise MaterialRoutingError("Native tool bindings must be explicit.")
    if not isinstance(objects, list) or len(objects) > 200:
        raise MaterialRoutingError("Invalid plate objects.")
    result = []
    seen = set()
    for object_ in objects:
        if not isinstance(object_, dict):
            raise MaterialRoutingError("Invalid model assignment.")
        instance = object_.get("instance_id")
        if not isinstance(instance, str) or not instance or instance in seen:
            raise MaterialRoutingError("Model instances must have unique identifiers.")
        seen.add(instance)
        slot = object_.get("material_slot")
        if slot is None:
            raise MaterialRoutingError("Assign a base filament to every model.")
        if (not isinstance(slot, dict) or
                str(slot.get("printer_id")) != str(printer_id)):
            raise MaterialRoutingError("A material assignment belongs to another printer.")
        slot_id = slot.get("slot_id")
        index = slot.get("slot_index")
        if not isinstance(slot_id, str) or not slot_id:
            raise MaterialRoutingError("Invalid physical filament slot.")
        if isinstance(index, bool) or not isinstance(index, int) or not 0 <= index <= 63:
            raise MaterialRoutingError("Invalid physical filament slot index.")
        if slot_id not in tool_bindings:
            raise MaterialRoutingError("No verified native tool mapping for slot " + slot_id + ".")
        tool = tool_bindings[slot_id]
        if isinstance(tool, bool) or not isinstance(tool, int) or not 0 <= tool <= 63:
            raise MaterialRoutingError("Invalid native tool index.")
        result.append(MaterialRoute(instance, str(printer_id), slot_id, index, tool))
    if topology == "independent_toolheads":
        # One physical head is dedicated to one filament, so reject
        # contradictory assignments to the same toolhead.
        heads = {}
        for item in result:
            previous = heads.setdefault(item.tool_index, item.slot_id)
            if previous != item.slot_id:
                raise MaterialRoutingError("Multiple physical slots target one independent printhead.")
    return result
