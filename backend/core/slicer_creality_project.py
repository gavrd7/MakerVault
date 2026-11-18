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
        if (not all(math.isfinite(v) for v in xs + ys) or
                min(xs) < -1e-5 or max(xs) > bed_width + 1e-5 or
                min(ys) < -1e-5 or max(ys) > bed_depth + 1e-5):
            raise SlicerProfileError("Creality positioned model exceeds the printable bed.")
    return data


# Native project settings use the *full* configuration. Creality's
# save_to_json emits scalar strings plus per-extruder arrays. These lists
# cover only keys known to represent per-filament or nozzle settings;
# unknown native settings are not guessed into multi-value arrays.
_PER_TOOL_KEYS = frozenset({
    "filament_colour", "filament_type", "filament_vendor",
    "filament_settings_id", "filament_ids", "filament_diameter",
    "filament_density", "filament_cost", "filament_max_volumetric_speed",
    "filament_flow_ratio", "filament_shrink", "filament_soluble",
    "filament_is_support", "filament_retraction_length",
    "filament_retraction_speed", "filament_loading_speed",
    "filament_loading_speed_start", "filament_unloading_speed",
    "filament_unloading_speed_start", "filament_toolchange_delay",
    "filament_cooling_final_speed", "filament_cooling_initial_speed",
    "filament_ramming_parameters", "filament_multitool_ramming",
    "nozzle_temperature", "nozzle_temperature_initial_layer",
    "nozzle_temperature_range_low", "nozzle_temperature_range_high",
    "bed_temperature", "bed_temperature_initial_layer",
    "cool_plate_temp", "cool_plate_temp_initial_layer",
    "hot_plate_temp", "hot_plate_temp_initial_layer",
    "textured_plate_temp", "textured_plate_temp_initial_layer",
    "eng_plate_temp", "eng_plate_temp_initial_layer",
    "supertack_plate_temp", "supertack_plate_temp_initial_layer",
    "chamber_temperatures", "required_nozzle_HRC",
    "fan_max_speed", "fan_min_speed", "overhang_fan_speed",
    "slow_down_layer_time", "slow_down_min_speed",
    "bridge_fan_speed", "enable_overhang_bridge_fan",
    "support_material_interface_fan_speed",
    "filament_start_gcode", "filament_end_gcode",
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
                "compatible_prints", "printer_model", "printer_variant"}
    project = {"version": version, "name": "project_settings", "from": "project"}
    for part in (machine, print_settings):
        for key, val in part.items():
            if key not in reserved:
                project[key] = _native_value(val)
    for key in _PER_TOOL_KEYS:
        present = [preset.get(key) for preset in filament_settings]
        if any(v is not None for v in present):
            if any(v is None for v in present):
                raise SlicerProfileError(
                    "Creality project palette is missing a required shared filament setting.")
            project[key] = [_native_value(v) for v in present]
    project["filament_settings_id"] = [
        str(preset.get("name") or "MakerVault filament %d" % (i + 1))
        for i, preset in enumerate(filament_settings)]
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
    entries["Metadata/project_settings.config"] = encoded
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED,
                         compresslevel=6, allowZip64=False) as dst:
        for name, blob in entries.items():
            dst.writestr(name, blob)
    result = output.getvalue()
    if len(result) > _MAX_PROJECT:
        raise SlicerProfileError("Creality project candidate exceeds the worker limit.")
    return result
