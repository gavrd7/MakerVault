"""Creality native 3MF placement-preservation preparation (not yet CLI-enabled).

Creality Print 7.3.1 requires embedded printer/process/filament config for
3MF project slicing; passing --load-settings or --load-filaments alongside a
project returns CLI_INVALID_PARAMS. This module prepares and verifies exact
MakerVault model placements before a separately verified profile packager.
"""
import io
import json
import math
import zipfile
from defusedxml import ElementTree as SafeET

from .slicer_plate_3mf import build_plate_3mf, NS
from .slicer_profiles import SlicerProfileError

_MAX_PROJECT = 32 * 1024 * 1024


def build_creality_positioned_plate(source_models, *, bed_width, bed_depth, tool_ids):
    """Return core 3MF with baked positions and per-object logical filament IDs.

    Input tools are zero-based, checked against the assigned palette. This is
    an intermediate geometry package, NOT a self-contained Creality project.
    Never send it to Creality's CLI before embedding verified native presets.
    """
    if (not isinstance(source_models, (list, tuple)) or
            not 2 <= len(source_models) <= 12 or
            not isinstance(tool_ids, (list, tuple)) or
            len(tool_ids) != len(source_models) or
            any(type(v) is not int or v not in (0, 1) for v in tool_ids) or
            set(tool_ids) != {0, 1}):
        raise SlicerProfileError("Creality positioned two-material plate has invalid assignments.")
    data = build_plate_3mf(
        list(source_models), bed_width=bed_width, bed_depth=bed_depth,
        native_tool_indices=list(tool_ids))
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
    xs = [border, bed_width - border - extent]
    ys = [border, bed_depth - border - extent]
    for x in xs:
        for y in ys:
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


def build_creality_project_candidate(plate, *, printer, process, filaments,
                                    version="7.3.1", prime_tower=None,
                                    bed_width=260, bed_depth=260):
    """Create a self-contained *candidate* Creality project 3MF.

    Deliberately not a verified CLI route. Project settings must first pass
    Creality's real loader/print result fixture before execution is enabled.
    """
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
    for key in _PER_TOOL_KEYS:
        present = [preset.get(key) for preset in filament_settings]
        if any(v is not None for v in present):
            if any(v is None for v in present):
                raise SlicerProfileError(
                    "Creality project palette is missing a required shared filament setting.")
            project[key] = [_one_filament_value(v, key) for v in present]
    project["filament_settings_id"] = [
        str(preset.get("name") or "MakerVault filament %d" % (i + 1))
        for i, preset in enumerate(filament_settings)]
    _native_palette_settings(project, filament_settings)
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
    if set(entries) != required:
        raise SlicerProfileError("Creality plate package has unexpected files.")
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
    if len(objects) != 2 or len(plate_nodes) != 1:
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
    for index in range(1, 3):
        ET.SubElement(assemble, "assemble_item", {
            "object_id": str(index), "instance_id": "0",
            "transform": "1 0 0 0 1 0 0 0 1 0 0 0",
            "offset": "0 0 0"})
    entries["Metadata/model_settings.config"] = ET.tostring(
        settings_root, encoding="utf-8", xml_declaration=True)
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
