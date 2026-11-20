"""Native flushing adapters for independent slicer engines and printer topologies.

The user-facing request belongs to slicer_flush_settings.py. This module
owns native Orca/Creality serialization and a *separate* capability
resolution axis for machine material-change mechanism. It never edits
manufacturer printer scripts or asserts physical purge effectiveness.
"""
from dataclasses import dataclass
import json
import math

from .slicer_material_routing import MaterialRoutingError
from .slicer_profiles import SlicerProfileError


@dataclass(frozen=True)
class FlushCapability:
    engine: str
    topology: str
    nozzle_count: int
    material_count: int
    supported: bool
    matrix_layout: str
    multiplier_encoding: str
    max_calculated_volume_mm3: int
    purge_validation: str = "native_unverified"


_ENGINE_FLUSH_FORMATS = {
    "orcaslicer": ("per_nozzle_vector", 20000),
    "crealityprint": ("scalar", 1200),
}
_ENGINE_ALIASES = {
    "orca": "orcaslicer", "orcaslicer": "orcaslicer",
    "creality": "crealityprint", "crealityprint": "crealityprint",
}
_TOPOLOGIES = frozenset({
    "single_nozzle_changer", "independent_toolheads", "toolchanger",
    "idex", "manual_filament_change", "single_material", "unknown",
})


def resolve_flush_capability(engine, topology, *, nozzle_count, material_count):
    """Describe capability without guessing from printer brand or name.

    Unknown engines/topologies fail closed; unsupported known topologies
    return a truthful, non-editable descriptor for UI/validation.
    Engine capability is *not* evidence that a firmware purge was executed.
    """
    if not isinstance(engine, str):
        raise MaterialRoutingError("Invalid slicer engine for flushing.")
    native = _ENGINE_ALIASES.get(engine.lower().strip())
    if native is None:
        raise MaterialRoutingError("No verified flushing adapter for selected slicer.")
    if topology not in _TOPOLOGIES:
        raise MaterialRoutingError("Unrecognized material-change topology.")
    if (type(nozzle_count) is not int or not 1 <= nozzle_count <= 16
            or type(material_count) is not int or not 1 <= material_count <= 16):
        raise MaterialRoutingError("Invalid verified nozzle/material counts.")
    multiplier, limit = _ENGINE_FLUSH_FORMATS[native]
    supported = (topology == "single_nozzle_changer"
                 and nozzle_count == 1 and material_count >= 2
                 and (native != "crealityprint" or material_count == 2))
    return FlushCapability(
        engine=native, topology=topology, nozzle_count=nozzle_count,
        material_count=material_count, supported=supported,
        matrix_layout="directional_row_major",
        multiplier_encoding=multiplier,
        max_calculated_volume_mm3=limit,
    )


def require_flush_capability(engine, topology, *, nozzle_count, material_count):
    capability = resolve_flush_capability(
        engine, topology, nozzle_count=nozzle_count, material_count=material_count)
    if not capability.supported:
        raise MaterialRoutingError(
            "Directional native flushing is unsupported for this verified "
            "slicer, nozzle count, material count or printer topology.")
    return capability


def map_verified_flush_transitions(transitions, bindings, tool_count):
    """Map user physical slots to native indices, preserving direction.

    Accept either the existing Orca MaterialRoute records or Creality's
    slot-to-tool dictionary. Detect conflicting and colliding mappings.
    The output has no firmware tool IDs and must not be used to send commands.
    """
    if type(tool_count) is not int or not 2 <= tool_count <= 16:
        raise MaterialRoutingError("Invalid native material count.")
    if isinstance(bindings, dict):
        pairs = list(bindings.items())
    elif isinstance(bindings, (list, tuple)):
        pairs = [(item.slot_id, item.tool_index) for item in bindings]
    else:
        raise MaterialRoutingError("Verified material bindings are required.")
    lookup = {}
    for slot, tool in pairs:
        if (not isinstance(slot, str) or not 1 <= len(slot) <= 128
                or type(tool) is not int or not 0 <= tool < tool_count):
            raise MaterialRoutingError("Invalid verified material binding.")
        old = lookup.setdefault(slot, tool)
        if old != tool:
            raise MaterialRoutingError("A physical material slot has conflicting native tools.")
    mapped = []
    seen = set()
    for change in transitions:
        source = lookup.get(change["from_slot_id"])
        destination = lookup.get(change["to_slot_id"])
        if source is None or destination is None or source == destination:
            raise MaterialRoutingError(
                "Flushing transition requires distinct verified physical-to-native bindings.")
        pair = (source, destination)
        if pair in seen:
            raise MaterialRoutingError("Multiple flushing transitions map to the same native tools.")
        seen.add(pair)
        mapped.append((source, destination, change["volume_mm3"]))
    return mapped



def apply_orca_native_flush(process_bytes, settings, *, routes, tool_count, topology):
    """Return a derived native process JSON with explicit matrix/tool mapping.

    Missing volume entries are inherited from the verified native process
    matrix. If that matrix is absent, every off-diagonal transition must be
    explicitly configured; zero is NOT a safe default for colour changes.
    """
    if settings is not None:
        require_flush_capability("orcaslicer", "single_nozzle_changer",
                                 nozzle_count=1, material_count=tool_count)
    from .slicer_flush_settings import validate_flush_settings
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
    # A multiplier-only or native prime-tower toggle changes no individual
    # tool-to-tool flush volume. Let Orca retain the original native profile
    # matrix/default instead of inventing an all-pairs replacement.
    if not approved["transitions"]:
        if approved["multiplier"] is not None:
            process["flush_multiplier"] = [str(approved["multiplier"])]
        if approved["prime_tower"] != "native":
            process["enable_prime_tower"] = (
                "1" if approved["prime_tower"] == "enabled" else "0")
        output = json.dumps(process, ensure_ascii=False, separators=(",", ":")).encode()
        if len(output) > 1024 * 1024:
            raise MaterialRoutingError("Native flushing settings exceed the profile size limit.")
        return output
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
    for from_tool, to_tool, volume in map_verified_flush_transitions(
            approved["transitions"], routes, tool_count):
        matrix[from_tool * tool_count + to_tool] = volume
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


def apply_creality_native_flush(project, settings, bindings):
    """Map explicit physical slot overrides to Creality's native T0/T1 matrix.

    The native project has four slots, but only two assigned tools. Keep the
    unassigned native entries unchanged. Never map on swatch colour/order.
    """
    if settings is not None:
        require_flush_capability("crealityprint", "single_nozzle_changer",
                                 nozzle_count=1, material_count=2)
    from .slicer_flush_settings import validate_flush_settings
    from .slicer_material_routing import MaterialRoutingError

    try:
        approved = validate_flush_settings(settings)
    except MaterialRoutingError as exc:
        raise SlicerProfileError(str(exc)) from exc
    if approved is None:
        return
    if not isinstance(bindings, dict) or set(bindings.values()) != {0, 1} or len(bindings) != 2:
        raise SlicerProfileError("Creality flushing requires exactly two verified filament-to-tool bindings.")
    if approved["multiplier"] is not None:
        # Creality Print PrintConfig.cpp declares flush_multiplier as coFloat
        # (scalar), unlike Orca 2.5's single-nozzle coFloats vector.
        # Preserve the validated user value in native project settings.
        project["flush_multiplier"] = str(approved["multiplier"])
    if approved["prime_tower"] != "native":
        project["enable_prime_tower"] = "1" if approved["prime_tower"] == "enabled" else "0"
    matrix = project.get("flush_volumes_matrix")
    if not isinstance(matrix, list) or len(matrix) != 16:
        raise SlicerProfileError("Creality native flush matrix is unavailable.")
    result = list(matrix)
    try:
        mapped = map_verified_flush_transitions(approved["transitions"], bindings, 2)
    except MaterialRoutingError as exc:
        raise SlicerProfileError("Creality flushing references an unmapped physical filament slot or conflicting mapping.") from exc
    for source, dest, volume in mapped:
        result[4 * source + dest] = str(volume)
    project["flush_volumes_matrix"] = result
    if approved["transitions"]:
        # Native Creality's explicit edited-volume flag is a coBool.
        project["flush_volumes_changed"] = "1"
