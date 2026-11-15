"""Provider-neutral material routing for slicer drafts.

An observed CFS/AMS bay is not a slicer extruder. Physical slots and native
tool indices have separate identities; only explicit verified bindings may
join them. This module never emits firmware commands.
"""
from dataclasses import dataclass


class MaterialRoutingError(ValueError):
    pass


TOPOLOGIES = frozenset({
    "single_nozzle_changer", "independent_toolheads", "toolchanger",
    "idex", "manual_filament_change",
})


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
    if topology in {"independent_toolheads", "toolchanger", "idex"}:
        # One physical head is dedicated to one filament, so reject
        # contradictory assignments to the same toolhead.
        heads = {}
        for item in result:
            previous = heads.setdefault(item.tool_index, item.slot_id)
            if previous != item.slot_id:
                raise MaterialRoutingError("Multiple physical slots target one independent printhead.")
    if topology == "idex" and any(item.tool_index > 1 for item in result):
        raise MaterialRoutingError("IDEX mode supports only its two distinct toolheads.")
    return result


def single_material_slice_assignment(objects, *, printer_id, selected_filament_profile_id,
                                     slot_filament_profiles=(), material_tool_bindings=()):
    """Validate an optional physical slot annotation for ONE logical filament.

    Slicing uses the already-selected native filament preset and logical tool 0.
    This does *not* claim to bind the resulting G-code to a physical feeder:
    that mapping is checked independently at printer submission.
    """
    if not isinstance(objects, list) or not objects:
        return None
    if not isinstance(slot_filament_profiles, (list, tuple)):
        raise MaterialRoutingError("Invalid slot filament profile list.")
    if not isinstance(material_tool_bindings, (list, tuple)):
        raise MaterialRoutingError("Invalid native tool binding list.")
    slots = [item.get("material_slot") for item in objects if isinstance(item, dict)]
    if len(slots) != len(objects):
        raise MaterialRoutingError("Invalid model material assignment.")
    assigned = [slot for slot in slots if slot is not None]
    if not assigned:
        if material_tool_bindings:
            raise MaterialRoutingError("Remove unused native tool bindings before slicing.")
        if slot_filament_profiles:
            raise MaterialRoutingError("Remove unused slot-specific filament presets before slicing.")
        return None
    if len(assigned) != len(slots):
        raise MaterialRoutingError("Assign the same filament slot to every model, or clear the assignments.")
    target = assigned[0]
    if not isinstance(target, dict) or set(target) != {"printer_id", "slot_id", "slot_index"}:
        raise MaterialRoutingError("Invalid physical material slot.")
    if str(target["printer_id"]) != str(printer_id):
        raise MaterialRoutingError("Assigned filament slot belongs to another printer.")
    slot_id = target["slot_id"]
    slot_index = target["slot_index"]
    if not isinstance(slot_id, str) or not 1 <= len(slot_id) <= 128:
        raise MaterialRoutingError("Invalid physical material slot ID.")
    if isinstance(slot_index, bool) or not isinstance(slot_index, int) or not 0 <= slot_index <= 63:
        raise MaterialRoutingError("Invalid physical material slot index.")
    if any(slot != target for slot in assigned[1:]):
        raise MaterialRoutingError("More than one filament slot requires verified multi-material slicing.")
    if material_tool_bindings:
        if (len(material_tool_bindings) != 1
                or material_tool_bindings[0] != {"slot_id": slot_id, "tool_index": 0}):
            raise MaterialRoutingError(
                "Single-filament slicing requires logical tool 0; other tool bindings need multi-material verification."
            )
    if len(slot_filament_profiles) > 1:
        raise MaterialRoutingError("Multi-filament native profile routing is not enabled.")
    if slot_filament_profiles:
        entry = slot_filament_profiles[0]
        if (not isinstance(entry, dict)
                or entry.get("slot_id") != slot_id
                or str(entry.get("profile_id")) != str(selected_filament_profile_id)):
            raise MaterialRoutingError(
                "The assigned slot's native filament preset must match the selected slicing preset."
            )
    return {"slot_id": slot_id, "slot_index": slot_index, "logical_tool": 0}


# Material-system declarations are adapter-owned. Never trust user-supplied
# topology or a physical tray number as an actual printer tool command.
ADAPTER_MATERIAL_SYSTEMS = {
    "creality_local": frozenset({"single_nozzle_changer"}),
    "bambu_local": frozenset({"single_nozzle_changer"}),
    "prusa": frozenset({"single_nozzle_changer", "independent_toolheads", "toolchanger"}),
    "moonraker": TOPOLOGIES,
    "octoprint": TOPOLOGIES,
    "snapmaker": frozenset({"single_nozzle_changer", "toolchanger", "independent_toolheads"}),
    "flashforge": frozenset({"single_nozzle_changer", "independent_toolheads"}),
    "anycubic": frozenset({"single_nozzle_changer", "independent_toolheads"}),
    "elegoo": frozenset({"single_nozzle_changer", "independent_toolheads"}),
    "qidi": frozenset({"single_nozzle_changer", "independent_toolheads"}),
    "other": TOPOLOGIES,
}


def detect_material_system(connections):
    """Use adapter-reported, explicit multi-material capability evidence only.

    Returns a known topology for slicing preparation. This is *not* proof of
    firmware toolchange commands or permission to submit multi-material G-code.
    Ambiguous/multiple sources are rejected instead of guessed.
    """
    detected = set()
    for connection in connections:
        if not connection.enabled or connection.status not in {"connected", "experimental"}:
            continue
        capabilities = connection.capabilities
        if not isinstance(capabilities, dict):
            continue
        material = capabilities.get("material_system")
        if not isinstance(material, dict) or material.get("available") is not True:
            continue
        topology = material.get("topology")
        if topology not in ADAPTER_MATERIAL_SYSTEMS.get(connection.adapter, frozenset()):
            continue
        detected.add(topology)
    if len(detected) != 1:
        raise MaterialRoutingError(
            "The printer's multi-material system could not be confirmed. "
            "Refresh its connection and verify the supported material adapter."
        )
    return detected.pop()


def derive_native_tool_order(objects, *, printer_id, topology):
    """Assign logical Orca filament indices by first model use, not tray position.

    Adapter-specific hardware routing is intentionally not emitted here.
    """
    if topology not in TOPOLOGIES:
        raise MaterialRoutingError("Unsupported material changeover system.")
    if not isinstance(objects, list) or not 2 <= len(objects) <= 200:
        raise MaterialRoutingError("Multi-material assignment needs at least two models.")
    unique_slots = []
    for item in objects:
        if not isinstance(item, dict) or not isinstance(item.get("material_slot"), dict):
            raise MaterialRoutingError("Choose a filament for every model.")
        slot = item["material_slot"]
        if str(slot.get("printer_id")) != str(printer_id):
            raise MaterialRoutingError("A filament belongs to a different printer.")
        slot_id = slot.get("slot_id")
        slot_index = slot.get("slot_index")
        if (not isinstance(slot_id, str) or not 1 <= len(slot_id) <= 128
                or not isinstance(slot_index, int) or isinstance(slot_index, bool)
                or not 0 <= slot_index <= 63):
            raise MaterialRoutingError("Invalid filament slot assignment.")
        if slot_id not in unique_slots:
            unique_slots.append(slot_id)
    if not 2 <= len(unique_slots) <= 16:
        raise MaterialRoutingError("Choose between two and sixteen different filaments.")
    bindings = {slot_id: index for index, slot_id in enumerate(unique_slots)}
    return bindings
