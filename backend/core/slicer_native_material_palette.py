"""Resolve an ordered, owner-scoped native filament palette for future worker use.

This module prepares only verified native preset bytes and tool indices. It
never dispatches jobs, writes printer commands, or enables multi-material
execution; worker support and real-binary acceptance remain separate gates.
"""
import json
import math

from .slicer_material_routing import MaterialRoutingError, plan_material_routes
from .slicer_native_resolution import resolved_native_profile


MAX_NATIVE_TOOLS = 16
MAX_PALETTE_BYTES = 8 * 1024 * 1024


def _single_positive_diameter(profile_json):
    """Return the native declared diameter, or None when unavailable."""
    value = profile_json.get("filament_diameter")
    if not isinstance(value, list) or len(value) != 1:
        return None
    try:
        if isinstance(value[0], bool):
            return None
        number = float(value[0])
    except (ValueError, TypeError):
        return None
    return number if math.isfinite(number) and 1 <= number <= 3.5 else None


def resolve_native_material_palette(
    objects, *, printer_id, owner_id, engine, engine_version,
    topology, tool_bindings, native_filament_profiles,
    resolver=resolved_native_profile,
):
    """Prepare validated palette bytes in exact zero-based native tool order.

    native_filament_profiles is a sequence of *selected* SlicerProfile records,
    including unused intermediate tool indices. Explicit bindings, not
    physical bay positions or colours, determine model-to-tool assignments.

    All selected native profiles must be owner-scoped, engine/version-matched,
    and already verified. The resolved byte blobs are never persisted here.
    No assumption is made that the worker accepts more than one filament.
    """
    if engine != "orcaslicer":
        raise MaterialRoutingError("Native multi-filament palette is not verified for this engine.")
    if (not isinstance(native_filament_profiles, (list, tuple))
            or not 2 <= len(native_filament_profiles) <= MAX_NATIVE_TOOLS):
        raise MaterialRoutingError("Select two to sixteen ordered native filament presets.")
    routes = plan_material_routes(
        objects, printer_id=printer_id, topology=topology,
        tool_bindings=tool_bindings,
    )
    if not routes or len({route.tool_index for route in routes}) < 2:
        raise MaterialRoutingError("Multi-material preparation requires two distinct assigned tools.")
    if any(route.tool_index >= len(native_filament_profiles) for route in routes):
        raise MaterialRoutingError("A model selects a native tool without a filament preset.")

    resolved = []
    diameters = []
    total_bytes = 0
    for profile in native_filament_profiles:
        if (getattr(profile, "owner_id", None) != owner_id
                or getattr(profile, "engine", None) != engine
                or getattr(profile, "engine_version", None) != engine_version
                or getattr(profile, "kind", None) != "filament"
                or getattr(profile, "status", None) != "verified"):
            raise MaterialRoutingError("A native filament preset is unverified or incompatible.")
        try:
            raw = resolver(profile)
            obj = json.loads(raw)
        except (ValueError, TypeError, UnicodeDecodeError, OSError) as exc:
            raise MaterialRoutingError("Could not resolve the native filament preset.") from exc
        if not isinstance(raw, bytes) or not isinstance(obj, dict):
            raise MaterialRoutingError("Invalid resolved native filament preset.")
        diameter = _single_positive_diameter(obj)
        if diameter is None:
            raise MaterialRoutingError("Native filament diameter is missing or invalid.")
        diameters.append(diameter)
        total_bytes += len(raw)
        if total_bytes > MAX_PALETTE_BYTES:
            raise MaterialRoutingError("Native filament palette exceeds the size limit.")
        resolved.append(raw)
    if max(diameters) - min(diameters) > 0.001:
        raise MaterialRoutingError("Mixed filament diameters cannot share one slicing job.")

    return {
        "routes": tuple(routes),
        "native_tool_indices": tuple(route.tool_index for route in routes),
        "filament_profiles": tuple(resolved),
        "topology": topology,
    }


def ordered_material_profile_ids(bindings, slot_profiles, *, main_profile_id):
    """Return native filament preset IDs in exact tool order, not bay order."""
    if (not isinstance(bindings, list) or not isinstance(slot_profiles, list)
            or not 2 <= len(bindings) <= MAX_NATIVE_TOOLS
            or len(slot_profiles) != len(bindings)):
        raise MaterialRoutingError("Choose 2–16 mapped tools and matching native filament presets.")
    mapping = {}
    for row in bindings:
        if (not isinstance(row, dict) or set(row) != {"slot_id", "tool_index"}
                or not isinstance(row["slot_id"], str)
                or not isinstance(row["tool_index"], int)
                or isinstance(row["tool_index"], bool)
                or row["slot_id"] in mapping):
            raise MaterialRoutingError("Invalid or duplicate material tool mapping.")
        mapping[row["slot_id"]] = row["tool_index"]
    tools = sorted(mapping.values())
    if tools != list(range(len(bindings))):
        raise MaterialRoutingError("Native tool indices must form a contiguous sequence starting at zero.")
    profiles = {}
    for row in slot_profiles:
        if (not isinstance(row, dict) or set(row) != {"slot_id", "profile_id"}
                or row["slot_id"] not in mapping
                or row["slot_id"] in profiles):
            raise MaterialRoutingError("Each physical slot needs one unique native filament preset.")
        profiles[row["slot_id"]] = row["profile_id"]
    if len(profiles) != len(mapping):
        raise MaterialRoutingError("Every mapped tool needs a matching native filament preset.")
    slots_by_tool = {tool:slot for slot, tool in mapping.items()}
    ordered = tuple(profiles[slots_by_tool[index]] for index in range(len(bindings)))
    if str(ordered[0]) != str(main_profile_id):
        raise MaterialRoutingError("Logical tool 0 must match the selected main filament preset.")
    return ordered


def prepare_multimaterial_plate(
    objects_with_stl, *, bed_width, bed_depth, printer_id, owner_id,
    engine, engine_version, topology, tool_bindings, native_filament_profiles,
    resolver=resolved_native_profile,
):
    """Prepare a native multi-filament 3MF and ordered palette for offline review.

    This function has NO scheduling or printer-submission side effects. The
    firmware's physical slot-to-tool command semantics, purge behaviour,
    painting and actual toolchange compatibility must be validated separately.
    """
    from .slicer_plate_3mf import build_plate_3mf

    if not isinstance(objects_with_stl, (list, tuple)) or not objects_with_stl:
        raise MaterialRoutingError("A multi-material plate needs models.")
    if len(objects_with_stl) > 12 or any(
        not isinstance(pair, tuple) or len(pair) != 2
        or not isinstance(pair[0], dict) or not isinstance(pair[1], bytes)
        for pair in objects_with_stl
    ):
        raise MaterialRoutingError("Invalid multi-material plate geometry.")
    objects = [item for item, _raw in objects_with_stl]
    result = resolve_native_material_palette(
        objects, printer_id=printer_id, owner_id=owner_id,
        engine=engine, engine_version=engine_version,
        topology=topology, tool_bindings=tool_bindings,
        native_filament_profiles=native_filament_profiles,
        resolver=resolver,
    )
    project = build_plate_3mf(
        objects_with_stl, bed_width=bed_width, bed_depth=bed_depth,
        native_tool_indices=result["native_tool_indices"],
    )
    return {
        "model_3mf": project,
        "filament_profiles": result["filament_profiles"],
        "native_tool_indices": result["native_tool_indices"],
        "topology": result["topology"],
        "printer_submission_verified": False,
    }
