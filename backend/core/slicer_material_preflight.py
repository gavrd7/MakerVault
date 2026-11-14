"""Offline multi-material job assembly; never queues, sends, or prints.

Unifies exact object identity/order, verified palette resolution, geometry
validation and native 3MF generation. The production admission path remains
independently blocked until a pinned real-engine and machine topology pass.
"""
from .slicer_material_routing import MaterialRoutingError
from .slicer_native_material_palette import resolve_native_material_palette
from .slicer_plate_3mf import build_plate_3mf
from .slicer_plate_validation import validate_plate_collisions
from .slicer_flush_settings import apply_orca_flush_settings


def prepare_offline_material_plate(
    objects_with_stl, *, bed_width, bed_depth,
    printer_id, owner_id, engine, engine_version, topology,
    tool_bindings, native_filament_profiles,
    resolver=None, native_process_profile=None, flush_settings=None,
):
    """Return a checked, separately routed native project and filament bytes.

    The objects' order determines each 3MF resource ID; route indices MUST
    match it. Material slots are advisory physical observations and mapping
    is explicit, never a direct trust in the CFS/AMS reported slot number.
    """
    if not isinstance(objects_with_stl, list) or not 2 <= len(objects_with_stl) <= 12:
        raise MaterialRoutingError("Offline material plate requires two to twelve meshes.")
    if any(not isinstance(entry, tuple) or len(entry) != 2
           or not isinstance(entry[0], dict) or not isinstance(entry[1], bytes)
           for entry in objects_with_stl):
        raise MaterialRoutingError("Invalid offline model or STL input.")
    objects = [item for item, _raw in objects_with_stl]
    options = dict(
        printer_id=printer_id, owner_id=owner_id, engine=engine,
        engine_version=engine_version, topology=topology,
        tool_bindings=tool_bindings,
        native_filament_profiles=native_filament_profiles,
    )
    if resolver is not None:
        options["resolver"] = resolver
    palette = resolve_native_material_palette(objects, **options)
    if tuple(obj["instance_id"] for obj in objects) != tuple(
            route.instance_id for route in palette["routes"]):
        raise MaterialRoutingError("Native model and material route order differ.")
    # Fail closed on mesh intersections before constructing an independent
    # toolpath, so overlapping materials cannot print over each other.
    validate_plate_collisions(objects_with_stl)
    model = build_plate_3mf(
        objects_with_stl, bed_width=bed_width, bed_depth=bed_depth,
        native_tool_indices=palette["native_tool_indices"],
    )
    native_process = None
    if flush_settings is not None:
        if not isinstance(native_process_profile, bytes):
            raise MaterialRoutingError(
                "A verified native process preset is required for flushing overrides.")
        native_process = apply_orca_flush_settings(
            native_process_profile, flush_settings, routes=palette["routes"],
            tool_count=len(palette["filament_profiles"]), topology=topology,
        )
    return {
        "native_process_profile": native_process,
        "model_3mf": model,
        "filament_profiles": palette["filament_profiles"],
        "native_tool_indices": palette["native_tool_indices"],
        "topology": topology,
        "routes": palette["routes"],
    }
