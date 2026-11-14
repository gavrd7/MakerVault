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
