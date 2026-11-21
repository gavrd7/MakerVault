"""Creality native 3MF placement-preservation preparation (not yet CLI-enabled).

Creality Print 7.3.1 requires embedded printer/process/filament config for
3MF project slicing; passing --load-settings or --load-filaments alongside a
project returns CLI_INVALID_PARAMS. This module prepares and verifies exact
MakerVault model placements before a separately verified profile packager.
"""
import io
import json
import math
import re
import zipfile
from defusedxml import ElementTree as SafeET

from .slicer_plate_3mf import build_plate_3mf, NS
from .slicer_profiles import SlicerProfileError

_MAX_PROJECT = 32 * 1024 * 1024


def build_creality_positioned_plate(source_models, *, bed_width, bed_depth, tool_ids, colour_tool_maps=None):
    """Return core 3MF with baked positions and per-object logical filament IDs.

    Input tools are zero-based, checked against the assigned palette. This is
    an intermediate geometry package, NOT a self-contained Creality project.
    Never send it to Creality's CLI before embedding verified native presets.
    """
    if (not isinstance(source_models, (list, tuple)) or
            not 1 <= len(source_models) <= 12 or
            not isinstance(tool_ids, (list, tuple)) or
            len(tool_ids) != len(source_models) or
            any(type(v) is not int or v not in (0, 1) for v in tool_ids) or
            (len(source_models) > 1 and set(tool_ids) != {0, 1}) or
            (len(source_models) == 1 and (colour_tool_maps is None or tool_ids[0] != 0))):
        raise SlicerProfileError("Creality positioned two-material plate has invalid assignments.")
    data = build_plate_3mf(
        list(source_models), bed_width=bed_width, bed_depth=bed_depth,
        native_tool_indices=list(tool_ids),
        native_colour_tools=list(colour_tool_maps) if colour_tool_maps is not None else None)
    if len(data) > _MAX_PROJECT:
        raise SlicerProfileError("Creality positioned plate exceeds the project limit.")
    ns = "{" + NS + "}"
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            model = SafeET.fromstring(archive.read("3D/3dmodel.model"))
            settings = SafeET.fromstring(archive.read("Metadata/model_settings.config"))
    except (KeyError, ValueError, OSError, zipfile.BadZipFile) as exc:
        raise SlicerProfileError("Creality positioned 3MF archive is incomplete.") from exc
    objects = model.findall("./" + ns + "resources/" + ns + "object")
    instances = model.findall("./" + ns + "build/" + ns + "item")
    settings_objects = settings.findall("object")
    if len(objects) != len(tool_ids) or len(instances) != len(tool_ids) or len(settings_objects) != len(tool_ids):
        raise SlicerProfileError("Creality positioned plate lost model identity.")
    for index, (obj, instance, record, tool) in enumerate(
            zip(objects, instances, settings_objects, tool_ids), 1):
        if obj.attrib.get("id") != str(index) or instance.attrib.get("objectid") != str(index):
            raise SlicerProfileError("Creality positioned plate has mismatched object identities.")
        if record.attrib.get("id") != str(index):
            raise SlicerProfileError("Creality positioned material metadata is misaligned.")
        extruders = [row.attrib.get("value") for row in record.findall("metadata")
                     if row.attrib.get("key") == "extruder"]
        if extruders != [str(tool + 1)]:
            raise SlicerProfileError("Creality positioned plate lost filament assignment.")
        if instance.attrib.get("transform") != "1 0 0 0 1 0 0 0 1 0 0 0":
            raise SlicerProfileError("Creality project positions must be baked into the mesh.")
        vertices = obj.findall("./" + ns + "mesh/" + ns + "vertices/" + ns + "vertex")
        if not vertices:
            raise SlicerProfileError("Creality positioned plate contains an empty model.")
        xs = [float(v.attrib["x"]) for v in vertices]
        ys = [float(v.attrib["y"]) for v in vertices]
        tolerance = 0.05  # mm; match the shared plate 3MF verifier
        if (not all(math.isfinite(v) for v in xs + ys) or
                min(xs) < -tolerance or max(xs) > bed_width + tolerance or
                min(ys) < -tolerance or max(ys) > bed_depth + tolerance):
            raise SlicerProfileError(
                "Creality model %d extends beyond the native %.1f × %.1f mm plate "
                "(X %.2f–%.2f, Y %.2f–%.2f mm)."
                % (index, bed_width, bed_depth,
                   min(xs), max(xs), min(ys), max(ys)))
    return data


# Native project settings use the *full* configuration. Creality's
# save_to_json emits scalar strings plus per-extruder arrays. These lists
# cover only keys known to represent per-filament or nozzle settings;
# unknown native settings are not guessed into multi-value arrays.
# Creality Print v7.3.1 src/libslic3r/Preset.cpp: s_Preset_filament_options.
# Compatibility and inheritance metadata are deliberately not print options.
_PER_TOOL_KEYS = frozenset({
    "activate_air_filtration",
    "activate_chamber_layer",
    "activate_chamber_temp_control",
    "additional_cooling_fan_speed",
    "bed_temperature",
    "bed_temperature_initial_layer",
    "chamber_temperature",
    "close_fan_the_first_x_layers",
    "complete_print_exhaust_fan_speed",
    "cool_cds_fan_start_at_height",
    "cool_plate_temp",
    "cool_plate_temp_initial_layer",
    "cool_special_cds_fan_speed",
    "cooling_perimeter_transition_distance",
    "cooling_slowdown_logic",
    "customized_plate_temp",
    "customized_plate_temp_initial_layer",
    "default_filament_colour",
    "during_print_exhaust_fan_speed",
    "enable_overhang_bridge_fan",
    "enable_pressure_advance",
    "enable_special_area_additional_cooling_fan",
    "eng_plate_temp",
    "eng_plate_temp_initial_layer",
    "epoxy_resin_plate_temp",
    "epoxy_resin_plate_temp_initial_layer",
    "fan_cooling_layer_time",
    "fan_max_speed",
    "fan_min_speed",
    "filament_adhesiveness_category",
    "filament_colour",
    "filament_cooling_final_speed",
    "filament_cooling_initial_speed",
    "filament_cooling_moves",
    "filament_cost",
    "filament_density",
    "filament_deretraction_speed",
    "filament_diameter",
    "filament_end_gcode",
    "filament_extruder_variant",
    "filament_flow_ratio",
    "filament_ids",
    "filament_is_support",
    "filament_load_time",
    "filament_loading_speed",
    "filament_loading_speed_start",
    "filament_long_retractions_when_cut",
    "filament_max_volumetric_speed",
    "filament_minimal_purge_on_wipe_tower",
    "filament_multitool_ramming",
    "filament_multitool_ramming_flow",
    "filament_multitool_ramming_volume",
    "filament_notes",
    "filament_nozzle_variant",
    "filament_ramming_parameters",
    "filament_retract_before_wipe",
    "filament_retract_length_toolchange",
    "filament_retract_lift_above",
    "filament_retract_lift_below",
    "filament_retract_lift_enforce",
    "filament_retract_restart_extra",
    "filament_retract_restart_extra_toolchange",
    "filament_retract_when_changing_layer",
    "filament_retraction_distances_when_cut",
    "filament_retraction_length",
    "filament_retraction_minimum_travel",
    "filament_retraction_speed",
    "filament_settings_id",
    "filament_shrink",
    "filament_shrinkage_compensation_z",
    "filament_soluble",
    "filament_stamping_distance",
    "filament_stamping_loading_speed",
    "filament_start_gcode",
    "filament_toolchange_delay",
    "filament_type",
    "filament_unload_time",
    "filament_unloading_speed",
    "filament_unloading_speed_start",
    "filament_vendor",
    "filament_wipe",
    "filament_wipe_distance",
    "filament_z_hop",
    "filament_z_hop_types",
    "full_fan_speed_layer",
    "hot_plate_temp",
    "hot_plate_temp_initial_layer",
    "idle_temperature",
    "material_flow_dependent_temperature",
    "material_flow_temp_graph",
    "nozzle_temperature",
    "nozzle_temperature_initial_layer",
    "nozzle_temperature_range_high",
    "nozzle_temperature_range_low",
    "overhang_fan_speed",
    "overhang_fan_threshold",
    "pellet_flow_coefficient",
    "pressure_advance",
    "reduce_fan_stop_start_freq",
    "required_nozzle_HRC",
    "slow_down_for_layer_cooling",
    "slow_down_layer_time",
    "slow_down_min_speed",
    "supertack_plate_temp",
    "supertack_plate_temp_initial_layer",
    "support_material_interface_fan_speed",
    "temperature_vitrification",
    "textured_plate_temp",
    "textured_plate_temp_initial_layer",
})


def _read_native_profile(blob, kind):
    if not isinstance(blob, bytes) or not blob or len(blob) > 4 * 1024 * 1024:
        raise SlicerProfileError("Creality native project profile exceeds the limit.")
    try:
        data = json.loads(blob.decode("utf-8-sig"))
    except (ValueError, UnicodeError) as exc:
        raise SlicerProfileError("Invalid Creality native project preset.") from exc
    if (not isinstance(data, dict) or data.get("type") not in (kind, None)
            or data.get("inherits") or len(data) > 4096):
        raise SlicerProfileError("Creality project requires resolved native presets.")
    # A project must never acquire executable post-processing or network
    # settings from an imported preset. Leave printer startup/toolchange
    # macros alone: they are legitimate machine firmware instructions.
    for key in data:
        if key.lower() in {
            "post_process", "post_process_script", "post_process_scripts",
            "post_processing_script", "upload_host", "upload_url",
            "print_host", "print_host_webui", "printhost_apikey",
        }:
            raise SlicerProfileError("Unsafe native project profile setting.")
    return data


def _native_value(value):
    if isinstance(value, bool):
        return "1" if value else "0"
    if isinstance(value, (int, float)):
        if not math.isfinite(value):
            raise SlicerProfileError("Non-finite native project setting.")
        return str(value)
    if isinstance(value, str):
        if len(value) > 65536:
            raise SlicerProfileError("Native project setting is oversized.")
        return value
    if isinstance(value, list):
        if len(value) > 32:
            raise SlicerProfileError("Native project setting array is oversized.")
        return [_native_value(v) for v in value]
    raise SlicerProfileError("Unsupported native project setting value.")


def _choose_safe_tower_position(plate, *, bed_width, bed_depth, width):
    """Find an unoccupied conservative square for a native prime tower.

    Tower depth may grow during multi-material slicing. This estimates a
    footprint for pre-slice placement only; the G-code extrusion audit remains
    authoritative and rejects an unexpectedly enlarged tower.
    """
    if not isinstance(width, (int, float)) or not math.isfinite(width) or not 5 <= width <= 100:
        raise SlicerProfileError("Unsupported Creality prime tower width.")
    extent = width + 12  # include brim and conservative spacing
    border = 5
    root = None
    with zipfile.ZipFile(io.BytesIO(plate)) as archive:
        root = SafeET.fromstring(archive.read("3D/3dmodel.model"))
    ns = "{" + NS + "}"
    occupied = []
    for obj in root.findall("./" + ns + "resources/" + ns + "object"):
        vertices = obj.findall("./" + ns + "mesh/" + ns + "vertices/" + ns + "vertex")
        if not vertices:
            raise SlicerProfileError("Empty Creality model.")
        xs = [float(vertex.attrib["x"]) for vertex in vertices]
        ys = [float(vertex.attrib["y"]) for vertex in vertices]
        occupied.append((min(xs) - 3, min(ys) - 3, max(xs) + 3, max(ys) + 3))
    # Prefer rear corners, then front corners. The earlier ordering selected
    # (5, 5) first on a mostly empty plate: the K2's front-left area. Avoid
    # that as the default while preserving native collision/bed bounds checks.
    # Explicit user placement is handled separately and is never overridden.
    candidates = (
        (bed_width - border - extent, bed_depth - border - extent),
        (border, bed_depth - border - extent),
        (bed_width - border - extent, border),
        (border, border),
    )
    for x, y in candidates:
            if x < 0 or y < 0:
                continue
            if all(x + extent < left or x > right or
                   y + extent < bottom or y > top
                   for left, bottom, right, top in occupied):
                return x, y
    raise SlicerProfileError(
        "No verified free corner for a Creality prime tower on this plate.")


def _one_filament_value(value, key):
    """Convert one resolved filament preset to a scalar for a native palette.

    Native preset JSON may contain scalar values or singleton vectors. The
    two-colour project needs a *flat* two-element vector per filament option,
    not a list of two lists which fails Creality's option parsing.
    """
    result = _native_value(value)
    if isinstance(result, list):
        if len(result) != 1 or isinstance(result[0], list):
            raise SlicerProfileError(
                "Native filament preset has an incompatible per-material setting: " + key)
        return result[0]
    return result


def _native_palette_settings(project, filaments, *, palette_slots=4):
    """Add Creality 7.3.x CFS-compatible vector and matrix dimensions.

    The native K2 reference has four logical filament positions even when
    only two are assigned to models. Unused positions are filled from an
    already-resolved and hash-checked native preset, not from any unknown
    CFS spool. They are not assigned to geometry and cannot start prints.
    """
    if len(filaments) != 2 or palette_slots != 4:
        raise SlicerProfileError("Unsupported Creality CFS palette size.")
    names = project.get("filament_settings_id")
    if not isinstance(names, list) or len(names) != 2:
        raise SlicerProfileError("Creality native filament identities are incomplete.")
    # Keep both active model material indices unchanged. Positions 3 and 4
    # are neutral placeholders until actual CFS routing can be established.
    project["filament_settings_id"] = names + [names[0], names[1]]
    for key, value in tuple(project.items()):
        if key in _PER_TOOL_KEYS and isinstance(value, list) and len(value) == 2:
            project[key] = [value[0], value[1], value[0], value[1]]
    # Creality Print treats filament_colour.size() as the number of physical
    # filaments in object_used_extruders(). Without this vector, its default
    # single entry makes extruder 2 look like a mixed/virtual filament and
    # raises "Unable to resolve a mixed filament used by the current plate."
    #
    # The underlying native filament preset can supply the actual colour.
    # When it does not, a display-only neutral is preferable to inventing
    # a CFS spool identity. The job is still diagnostic-only until the
    # physical CFS slot mapping and resulting G-code are independently audited.
    colours = project.get("filament_colour")
    if colours is None:
        colour_sources = project.get("default_filament_colour")
        if not isinstance(colour_sources, list) or len(colour_sources) not in (2, 4):
            colour_sources = None
        if colour_sources is None:
            colours = ["#FFFFFF"] * palette_slots
        else:
            colours = [value if isinstance(value, str) and
                       len(value) == 7 and value.startswith("#") and
                       all(ch in "0123456789abcdefABCDEF" for ch in value[1:])
                       else "#FFFFFF" for value in colour_sources]
            if len(colours) == 2:
                colours *= 2
        project["filament_colour"] = colours
    elif (not isinstance(colours, list) or len(colours) not in (2, palette_slots)
          or any(not isinstance(value, str) or len(value) != 7 or
                 not value.startswith("#") or
                 any(ch not in "0123456789abcdefABCDEF" for ch in value[1:])
                 for value in colours)):
        raise SlicerProfileError("Invalid Creality physical filament colour palette.")
    else:
        if len(colours) == 2:
            project["filament_colour"] = colours * 2
    defaults = {
        "filament_map": ["1"] * palette_slots,
        "filament_map_2": ["0"] * palette_slots,
        "filament_map_mode": "AutoForSaving",
        "filament_colour_type": ["1"] * palette_slots,
        "filament_volume_map": ["0"] * palette_slots,
        "filament_nozzle_variant": ["0"] * palette_slots,
        "filament_multi_colour": ["#000000"] * palette_slots,
        "filament_ids": [""] * palette_slots,
        "default_filament_colour": [""] * palette_slots,
        "nozzle_flush_dataset": ["0"],
    }
    for key, values in defaults.items():
        existing = project.get(key)
        if existing is None:
            project[key] = values
        elif isinstance(values, list) and isinstance(existing, list) and len(existing) != len(values):
            if len(existing) == 1 and len(values) == palette_slots:
                project[key] = existing * palette_slots
            elif len(existing) == 2 and len(values) == palette_slots:
                project[key] = existing * 2
            else:
                raise SlicerProfileError("Invalid native Creality vector size: " + key)
    # Non-zero conservative diagnostic purge volumes for material changes.
    # Never silently disable purging by generating an all-zero matrix.
    # Actual CFS flushing values must be audited before print approval.
    project.setdefault("flush_volumes_matrix", [
        "0" if source == destination else "140"
        for source in range(palette_slots)
        for destination in range(palette_slots)
    ])
    project.setdefault("flush_volumes_vector", ["140"] * (palette_slots * 2))
    matrix = project["flush_volumes_matrix"]
    vector = project["flush_volumes_vector"]
    if isinstance(matrix, list) and len(matrix) == 4:
        # Expand a source 2x2 matrix by repeating its material-specific
        # transition values for unassigned virtual slots.
        project["flush_volumes_matrix"] = [
            matrix[(source % 2) * 2 + (destination % 2)]
            for source in range(palette_slots)
            for destination in range(palette_slots)]
    if isinstance(vector, list) and len(vector) == 4:
        project["flush_volumes_vector"] = vector * 2
    if (not isinstance(project["flush_volumes_matrix"], list) or
            len(project["flush_volumes_matrix"]) != palette_slots ** 2 or
            not isinstance(project["flush_volumes_vector"], list) or
            len(project["flush_volumes_vector"]) != palette_slots * 2):
        raise SlicerProfileError("Creality CFS purge matrix does not match the native material palette.")
    project.setdefault("enable_filament_dynamic_map", "0")
    return palette_slots


def _apply_creality_flush_settings(project, settings, bindings):
    """Compatibility entrypoint for native Creality project flushing.

    Keep printer/project generation separate from the Creality serializer.
    Do not replace, synthesise or edit manufacturer machine G-code.
    """
    from .slicer_flush_adapters import apply_creality_native_flush
    return apply_creality_native_flush(project, settings, bindings)


_CREALITY_SUPPORT_OVERRIDE_KEYS = frozenset({
    "enable_support", "support_type", "support_threshold_angle",
    "minimum_support_area", "support_remove_small_overhang",
    "support_on_build_plate_only", "support_critical_regions_only",
    "bridge_no_support", "max_bridge_length",
})


def _mark_creality_support_overrides(project, keys):
    """Preserve explicit support options across Creality 7.3.x preset reload.

    CLI SliceCommand::refresh_creality_project_configuration passes project
    settings through PresetBundle::load_config_model. Its process-preset
    loader honors different_settings_to_system[0] as the list of intentionally
    overridden process keys; merely writing values into the project JSON is
    not enough. The real Creality desktop project uses this exact convention.
    """
    selected = set(keys)
    if not selected or not selected <= _CREALITY_SUPPORT_OVERRIDE_KEYS:
        raise SlicerProfileError("Invalid Creality support override keys.")
    palette = project.get("filament_settings_id")
    if not isinstance(palette, list) or len(palette) not in (2, 4):
        raise SlicerProfileError("Creality support override requires a verified filament palette.")
    width = len(palette) + 2
    value = project.get("different_settings_to_system")
    if value is None:
        value = [""] * width
    elif (not isinstance(value, list) or len(value) != width
          or any(not isinstance(row, str) or len(row) > 8192 for row in value)):
        raise SlicerProfileError("Creality preset override vector is malformed.")
    else:
        value = list(value)
    # These are native semicolon-separated process setting identifiers.
    # Retain any existing process overrides and all other preset slots.
    existing = [key for key in value[0].split(";") if key]
    if any(not re.fullmatch(r"[a-z][a-z0-9_]{0,79}", key) for key in existing):
        raise SlicerProfileError("Creality process override identifier is malformed.")
    for key in sorted(selected):
        if key not in existing:
            existing.append(key)
    value[0] = ";".join(existing)
    project["different_settings_to_system"] = value



def _mark_creality_flush_preset_overrides(project, settings, *, machine, process):
    """Declare exactly the user-selected flush settings in native preset slots.

    The Creality CLI recreates process and machine presets from system defaults.
    The embedded values only survive as explicit different_settings_to_system
    overrides in their correct respective preset categories.
    """
    from .slicer_flush_settings import validate_flush_settings
    from .slicer_material_routing import MaterialRoutingError
    try:
        selected = validate_flush_settings(settings)
    except MaterialRoutingError as exc:
        raise SlicerProfileError(str(exc)) from exc
    if selected is None:
        return
    palette = project.get("filament_settings_id")
    if not isinstance(palette, list) or len(palette) != 4:
        raise SlicerProfileError("Creality flush overrides require a verified four-slot palette.")
    rows = project.get("different_settings_to_system")
    if (not isinstance(rows, list) or len(rows) != len(palette) + 2
            or any(not isinstance(row, str) or len(row) > 8192 for row in rows)):
        raise SlicerProfileError("Invalid native Creality flush override vector.")
    updated = list(rows)
    process_keys = set()
    if selected["multiplier"] is not None:
        process_keys.add("flush_multiplier")
    if selected["transitions"]:
        process_keys.update({"flush_volumes_matrix", "flush_volumes_changed"})
    if selected["prime_tower"] != "native":
        process_keys.add("enable_prime_tower")
    # Only retain an explicitly selected process profile value; do not invent
    # a prime volume or overwrite vendor printer macros.
    if "prime_volume" in process:
        process_keys.add("prime_volume")
    printer_keys = set()
    # The route belongs to machine settings. Keep its original value,
    # including disabled, rather than silently enabling purge in tower.
    if "purge_in_prime_tower" in machine:
        printer_keys.add("purge_in_prime_tower")
    for index, keys in ((0, process_keys), (len(palette) + 1, printer_keys)):
        if not keys:
            continue
        existing = [key for key in updated[index].split(";") if key]
        if any(not re.fullmatch(r"[a-z][a-z0-9_]{0,79}", key) for key in existing):
            raise SlicerProfileError("Malformed native Creality flush override key.")
        for key in sorted(keys):
            if key not in project:
                raise SlicerProfileError("Missing requested native Creality flush option.")
            if key not in existing:
                existing.append(key)
        updated[index] = ";".join(existing)
        if len(updated[index]) > 8192:
            raise SlicerProfileError("Native Creality flush override list is too long.")
    project["different_settings_to_system"] = updated


def _preserve_creality_machine_multicolor_capability(project, machine, *,
                                                  require_verified=False):
    """Preserve explicitly selected *machine* capability through the 3MF CLI.

    Creality's GUI edits this property on its machine preset. A default,
    missing, inferred-from-printer-name, or experimental value is not an
    approved source. The toolchange script must remain vendor-authored.
    """
    if type(require_verified) is not bool:
        raise SlicerProfileError("Invalid Creality machine capability validation mode.")
    selected = machine.get("multicolor_method")
    if selected is None:
        if require_verified:
            raise SlicerProfileError(
                "Creality multicolour requires a selected native machine preset "
                "with explicitly enabled multicolor_method; the original K2 "
                "profile has no such capability. Do not print this slice.")
        return False
    if type(selected) is bool:
        enabled = selected
    elif type(selected) is str and selected in {"0", "1"}:
        enabled = selected == "1"
    elif type(selected) is int and selected in (0, 1):
        enabled = selected == 1
    else:
        raise SlicerProfileError("Invalid native Creality multicolor_method machine value.")
    if require_verified and not enabled:
        raise SlicerProfileError(
            "Selected Creality machine preset disables manufacturer multicolour purge.")
    # Never synthesize a script or a capability. For a printer-ready
    # validation demand, require the manufacturer's known gating structure.
    script = machine.get("change_filament_gcode")
    if require_verified and (
            not isinstance(script, str)
            or not script.lstrip().startswith("{if multicolor_method}")
            or "flush_length_1" not in script
            or "M8200" not in script):
        raise SlicerProfileError(
            "Selected Creality machine preset has no verified native "
            "multicolour purge script; printer-ready slicing is blocked.")
    rows = project.get("different_settings_to_system")
    palette = project.get("filament_settings_id")
    if (not isinstance(palette, list) or len(palette) != 4
            or not isinstance(rows, list) or len(rows) != len(palette) + 2
            or any(not isinstance(row, str) or len(row) > 8192 for row in rows)):
        raise SlicerProfileError("Invalid Creality native printer capability overrides.")
    marker = "multicolor_method"
    existing = [key for key in rows[-1].split(";") if key]
    if any(not re.fullmatch(r"[a-z][a-z0-9_]{0,79}", key) for key in existing):
        raise SlicerProfileError("Invalid Creality printer setting override key.")
    if marker not in existing:
        existing.append(marker)
    rows = list(rows)
    rows[-1] = ";".join(existing)
    project["different_settings_to_system"] = rows
    project[marker] = "1" if enabled else "0"
    return enabled


def build_creality_project_candidate(plate, *, printer, process, filaments,
                                    version="7.3.1", prime_tower=None,
                                    tool_colours=None, flush_settings=None,
                                    tool_bindings=None, layer_ranges=None,
                                    bed_width=260, bed_depth=260,
                                    preserve_native_flush_overrides=True,
                                    require_verified_multicolor_purge=False):
    """Create a self-contained *candidate* Creality project 3MF.

    Deliberately not a verified CLI route. Project settings must first pass
    Creality's real loader/print result fixture before execution is enabled.
    """
    if type(preserve_native_flush_overrides) is not bool:
        raise SlicerProfileError("Invalid native Creality flush override preservation mode.")
    if type(require_verified_multicolor_purge) is not bool:
        raise SlicerProfileError("Invalid native Creality machine purge requirement.")
    if not isinstance(plate, bytes) or len(plate) > _MAX_PROJECT:
        raise SlicerProfileError("Invalid Creality plate archive.")
    if not isinstance(filaments, (list, tuple)) or len(filaments) != 2:
        raise SlicerProfileError("Creality project candidate needs two assigned filaments.")
    if not isinstance(version, str) or not version.startswith("7.3."):
        raise SlicerProfileError("Unapproved Creality project version.")
    machine = _read_native_profile(printer, "machine")
    print_settings = _read_native_profile(process, "process")
    filament_settings = [_read_native_profile(blob, "filament") for blob in filaments]
    reserved = {"type", "from", "name", "setting_id", "inherits",
                "instantiation", "version", "compatible_printers",
                "compatible_prints"}
    project = {"version": version, "name": "project_settings", "from": "project"}
    for part in (machine, print_settings):
        for key, val in part.items():
            if key not in reserved:
                project[key] = _native_value(val)
    # Native machine presets store the bed polygon as a comma-separated
    # string. The Creality desktop *project* stores each vertex separately.
    # Parse only the previously verified origin-aligned rectangle, so the
    # project cannot silently change printable dimensions or exclusion zones.
    raw_area = project.get("printable_area")
    if isinstance(raw_area, str):
        import re
        points = [point.strip() for point in raw_area.split(",")]
        if len(points) == 5 and points[-1] == points[0]:
            points.pop()
        match = [re.fullmatch(r"([+-]?\d+(?:\.\d+)?)x([+-]?\d+(?:\.\d+)?)", point)
                 for point in points]
        if len(points) != 4 or any(m is None for m in match):
            raise SlicerProfileError("Invalid native Creality project printable polygon.")
        parsed = [(float(m.group(1)), float(m.group(2))) for m in match]
        if (not all(math.isfinite(x) and math.isfinite(y) for x, y in parsed)
                or set(parsed) != {(0.0, 0.0), (float(bed_width), 0.0),
                                   (float(bed_width), float(bed_depth)),
                                   (0.0, float(bed_depth))}):
            raise SlicerProfileError("Native Creality project polygon does not match the verified bed.")
        project["printable_area"] = points
    # Creality Print v7.3.1 src/libslic3r/PrintConfig.cpp declares both
    # customized_plate_temp and customized_plate_temp_initial_layer as coInts
    # with an explicit default of 35 C. Some genuine official filament
    # presets leave these options absent while another material defines an
    # override. Use only that audited engine default for the missing tool,
    # never the OTHER material's temperature (and never a guessed default).
    creality_native_defaults = {
        "customized_plate_temp": "35",
        "customized_plate_temp_initial_layer": "35",
    }
    for key in _PER_TOOL_KEYS:
        present = [preset.get(key) for preset in filament_settings]
        if any(v is not None for v in present):
            if any(v is None for v in present):
                # Preserve explicit per-tool values; use only defaults
                # verified in Creality Print's own v7.3.1 PrintConfig.cpp.
                if key == "filament_shrinkage_compensation_z":
                    present = ["100%" if v is None else v for v in present]
                elif version == "7.3.1" and key in creality_native_defaults:
                    present = [
                        creality_native_defaults[key] if v is None else v
                        for v in present
                    ]
                else:
                    missing = ", ".join("T%d" % i for i, value in enumerate(present)
                                        if value is None)
                    raise SlicerProfileError(
                        "Creality filament presets disagree on native setting "
                        + key + " (missing for " + missing + "). "
                        "Select compatible native filament profiles.")
            project[key] = [_one_filament_value(v, key) for v in present]
    project["filament_settings_id"] = [
        str(preset.get("name") or "MakerVault filament %d" % (i + 1))
        for i, preset in enumerate(filament_settings)]
    # Selected slot colours override neutral preset defaults. These are
    # material display colours, not evidence of a physical CFS route.
    if tool_colours is not None:
        if (not isinstance(tool_colours, (list, tuple))
                or len(tool_colours) != 2
                or any(not isinstance(colour, str) or len(colour) != 7
                       or colour[0] != "#" or
                       any(c not in "0123456789abcdefABCDEF" for c in colour[1:])
                       for colour in tool_colours)):
            raise SlicerProfileError("Invalid Creality selected filament colour palette.")
        project["filament_colour"] = [colour.upper() for colour in tool_colours]
    _native_palette_settings(project, filament_settings)
    # Creality's project loader restores a system print preset and otherwise
    # discards non-default support options from project_settings.config.
    # Mark only explicitly selected native support keys, not arbitrary user
    # JSON or printer/filament G-code settings.
    _mark_creality_support_overrides(
        project, ("enable_support", "support_type"))
    # Preserve only the selected machine preset's explicit capability. Never
    # infer it from a K2 name, CFS material count, or the diagnostic probe.
    _preserve_creality_machine_multicolor_capability(
        project, machine, require_verified=require_verified_multicolor_purge)
    if flush_settings is not None:
        _apply_creality_flush_settings(project, flush_settings, tool_bindings)
        # The ordinary builder retains native values through the CLI preset
        # merger. Only the explicit historical negative-control diagnostics
        # may opt out, so they still test unmarked project behaviour.
        if preserve_native_flush_overrides:
            _mark_creality_flush_preset_overrides(
                project, flush_settings, machine=machine, process=print_settings)
    # Creality 7.3.1 uses one-based physical nozzle routing. A K2/CFS
    # changes filament through a single physical nozzle; it does not have
    # two physical nozzle_diameter entries. Native upstream tests explicitly
    # accept [1, 1] for two filaments / one nozzle.
    nozzles = project.get("nozzle_diameter")
    if isinstance(nozzles, list) and len(nozzles) == 1:
        project["filament_map"] = ["1", "1", "1", "1"]
    project["print_settings_id"] = str(print_settings.get("name") or "MakerVault process")
    project["printer_settings_id"] = str(machine.get("name") or "MakerVault printer")
    if prime_tower is None and project.get("enable_prime_tower", "1") != "0":
        raw = project.get("prime_tower_width", "40")
        tower_width = float(raw[0] if isinstance(raw, list) else raw)
        x, y = _choose_safe_tower_position(
            plate, bed_width=bed_width, bed_depth=bed_depth,
            width=tower_width)
        prime_tower = {"x": x, "y": y}
    if prime_tower is not None:
        if not isinstance(prime_tower, dict) or set(prime_tower) != {"x", "y"}:
            raise SlicerProfileError("Invalid Creality prime tower coordinates.")
        x, y = prime_tower["x"], prime_tower["y"]
        if (any(isinstance(v, bool) or not isinstance(v, (int, float))
                or not math.isfinite(v) for v in (x, y))
                or not 0 <= x < bed_width or not 0 <= y < bed_depth):
            raise SlicerProfileError("Creality prime tower is outside the printable bed.")
        project["wipe_tower_x"] = [str(round(x, 3))]
        project["wipe_tower_y"] = [str(round(y, 3))]
    encoded = json.dumps(project, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    if len(encoded) > 4 * 1024 * 1024:
        raise SlicerProfileError("Creality project settings exceed safe limits.")
    try:
        with zipfile.ZipFile(io.BytesIO(plate)) as source:
            entries = {name: source.read(name) for name in source.namelist()}
    except (zipfile.BadZipFile, OSError, ValueError) as exc:
        raise SlicerProfileError("Invalid Creality plate package.") from exc
    required = {"3D/3dmodel.model", "Metadata/model_settings.config",
                "_rels/.rels", "[Content_Types].xml"}
    optional = {"Metadata/layer_config_ranges.xml"} if layer_ranges is not None else set()
    if not required.issubset(entries) or set(entries) - required - optional:
        raise SlicerProfileError("Creality plate package has unexpected files.")
    if layer_ranges is None and "Metadata/layer_config_ranges.xml" in entries:
        # Do not quietly strip an edited layer range from a native project.
        raise SlicerProfileError("Creality layer ranges require explicit validation.")
    if layer_ranges is not None and entries.get("Metadata/layer_config_ranges.xml") != layer_ranges:
        raise SlicerProfileError("Creality native layer range metadata changed during project preparation.")
    # The 3MF model's Application metadata is what the native importer
    # actually reads into its Semver file_version. An AppVersion value only
    # in Metadata/creality.config leaves it at 0.0.0 and causes CLI -24
    # (Linux exit 232, unsupported project version).
    try:
        root = SafeET.fromstring(entries["3D/3dmodel.model"])
        if root.tag != "{" + NS + "}model":
            raise SlicerProfileError("Creality 3MF has no native model root.")
        for node in list(root):
            if node.tag == "{" + NS + "}metadata" and node.get("name") == "Application":
                root.remove(node)
        from xml.etree import ElementTree as ET
        application = ET.Element("{" + NS + "}metadata", {"name": "Application"})
        application.text = "Creality_Print V" + version
        root.insert(0, application)
        entries["3D/3dmodel.model"] = SafeET.tostring(
            root, encoding="utf-8", xml_declaration=True)
    except (ValueError, SafeET.ParseError) as exc:
        raise SlicerProfileError("Creality 3MF model metadata is invalid.") from exc
    # Creality's own project includes per-object part, plate and assemble
    # records. Identity transforms are essential: MakerVault positions are
    # already baked into the verified mesh and MUST NOT be applied twice.
    settings_root = SafeET.fromstring(entries["Metadata/model_settings.config"])
    from xml.etree import ElementTree as ET
    objects = settings_root.findall("object")
    plate_nodes = settings_root.findall("plate")
    if not 1 <= len(objects) <= 2 or len(plate_nodes) != 1:
        raise SlicerProfileError("Creality model settings do not match two prepared objects.")
    for index, object_node in enumerate(objects, 1):
        if object_node.get("id") != str(index):
            raise SlicerProfileError("Native Creality object IDs are inconsistent.")
        if not any(child.get("key") == "name" for child in object_node.findall("metadata")):
            ET.SubElement(object_node, "metadata", {
                "key": "name", "value": "Model " + str(index)})
        if object_node.find("part") is None:
            part = ET.SubElement(object_node, "part", {
                "id": "1", "subtype": "normal_part"})
            ET.SubElement(part, "metadata", {
                "key": "name", "value": "Model " + str(index)})
            ET.SubElement(part, "metadata", {
                "key": "matrix", "value":
                "1 0 0 0 0 1 0 0 0 0 1 0 0 0 0 1"})
    plate_node = plate_nodes[0]
    if not any(child.get("key") == "locked" for child in plate_node.findall("metadata")):
        ET.SubElement(plate_node, "metadata", {
            "key": "locked", "value": "false"})
    assemble = settings_root.find("assemble")
    if assemble is None:
        assemble = ET.SubElement(settings_root, "assemble")
    if list(assemble):
        raise SlicerProfileError("Unexpected pre-existing Creality assembly metadata.")
    for index in range(1, len(objects) + 1):
        ET.SubElement(assemble, "assemble_item", {
            "object_id": str(index), "instance_id": "0",
            "transform": "1 0 0 0 1 0 0 0 1 0 0 0",
            "offset": "0 0 0"})
    entries["Metadata/model_settings.config"] = ET.tostring(
        settings_root, encoding="utf-8", xml_declaration=True)
    if layer_ranges is not None:
        # Creality's bbs_3mf importer accepts the same Bambu/Orca-style
        # Metadata/layer_config_ranges.xml object-range format.
        # The source-model builder already validates band bounds and geometry.
        if (not isinstance(layer_ranges, bytes) or len(layer_ranges) > 128 * 1024):
            raise SlicerProfileError("Invalid Creality native layer range metadata.")
        try:
            layer_root = SafeET.fromstring(layer_ranges)
        except SafeET.ParseError as exc:
            raise SlicerProfileError("Invalid Creality native layer range XML.") from exc
        if layer_root.tag != "objects":
            raise SlicerProfileError("Invalid Creality native layer range root.")
        entries["Metadata/layer_config_ranges.xml"] = layer_ranges
    entries["Metadata/project_settings.config"] = encoded
    # Creality 7.3.1 checks this metadata before accepting the file as a
    # native project. It is separate from the effective project settings.
    from xml.etree import ElementTree as ET
    meta = ET.Element("config")
    for key, value in (
        ("Company", "Creality"),
        ("Application", "Creality_Print"),
        ("AppVersion", version),
        ("FileVersion", "1.0"),
        ("FileType", "Undefined"),
    ):
        ET.SubElement(meta, "metadata", {"key": key, "value": value})
    entries["Metadata/creality.config"] = ET.tostring(
        meta, encoding="utf-8", xml_declaration=True)
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED,
                         compresslevel=6, allowZip64=False) as dst:
        for name, blob in entries.items():
            dst.writestr(name, blob)
    result = output.getvalue()
    if len(result) > _MAX_PROJECT:
        raise SlicerProfileError("Creality project candidate exceeds the worker limit.")
    return result
