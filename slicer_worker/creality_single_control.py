"""Derive a true single-object / single-filament CLI control from a validated
two-model MakerVault Creality candidate, without changing either original.

Diagnostic transformation only; NOT a production Creality 3MF builder.
"""
import io
import json
import zipfile
from xml.etree import ElementTree as ET

MODEL_NS = "{http://schemas.microsoft.com/3dmanufacturing/core/2015/02}"
SETTINGS = "Metadata/project_settings.config"
MANIFEST = "Metadata/model_settings.config"
MODEL = "3D/3dmodel.model"
SLOT_KEYS = {
    "filament_map", "filament_map_2", "filament_colour_type",
    "filament_volume_map", "filament_nozzle_variant", "filament_ids",
    "default_filament_colour", "filament_multi_colour",
    "nozzle_temperature", "nozzle_temperature_initial_layer",
    "cool_plate_temp", "hot_plate_temp", "textured_plate_temp",
    "fan_min_speed", "fan_max_speed",
}


def single_material_control(candidate):
    """Keep first model only; reduce *material* vectors to one entry.

    This isolates multi-material project validation from single-material
    structural validity. Do not confuse it with a project exported by the
    Creality desktop application.
    """
    with zipfile.ZipFile(io.BytesIO(candidate)) as src:
        config = json.loads(src.read(SETTINGS))
        slots = config.get("filament_settings_id")
        if not isinstance(slots, list) or len(slots) < 2:
            raise ValueError("A two-material candidate is required.")
        model = ET.fromstring(src.read(MODEL))
        resources = model.find(MODEL_NS + "resources")
        build = model.find(MODEL_NS + "build")
        if resources is None or build is None:
            raise ValueError("Candidate lacks valid 3MF geometry.")
        objects = resources.findall(MODEL_NS + "object")
        builds = build.findall(MODEL_NS + "item")
        if len(objects) != 2 or len(builds) != 2:
            raise ValueError("Single-control expects two prepared meshes.")
        kept_id = builds[0].get("objectid")
        if kept_id != objects[0].get("id"):
            raise ValueError("Unexpected first-object relationship.")
        for obj in objects[1:]:
            resources.remove(obj)
        for item in builds[1:]:
            build.remove(item)
        manifest = ET.fromstring(src.read(MANIFEST))
        obj_nodes = manifest.findall("object")
        if len(obj_nodes) != 2:
            raise ValueError("Unexpected model settings records.")
        for obj in obj_nodes:
            if obj.get("id") != kept_id:
                manifest.remove(obj)
        first = manifest.find("object")
        for meta in first.findall("metadata"):
            if meta.get("key") == "extruder":
                meta.set("value", "1")
        plate = manifest.find("plate")
        if plate is None:
            raise ValueError("Missing native build plate metadata.")
        for item in plate.findall("model_instance"):
            ref = next((meta.get("value") for meta in item.findall("metadata")
                        if meta.get("key") == "object_id"), None)
            if ref != kept_id:
                plate.remove(item)
        assembly = manifest.find("assemble")
        if assembly is not None:
            for item in assembly.findall("assemble_item"):
                if item.get("object_id") != kept_id:
                    assembly.remove(item)
        for key, value in list(config.items()):
            if not isinstance(value, list) or len(value) != len(slots):
                continue
            if key.startswith("filament_") or key in SLOT_KEYS:
                config[key] = value[:1]
        config["filament_settings_id"] = slots[:1]
        config["filament_map"] = ["1"]
        config["filament_map_2"] = ["0"]
        config["flush_volumes_matrix"] = ["0"]
        config["flush_volumes_vector"] = ["140", "140"]
        config["enable_prime_tower"] = "0"
        config.pop("wipe_tower_x", None)
        config.pop("wipe_tower_y", None)
        output = io.BytesIO()
        with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as out:
            for name in src.namelist():
                if name == MODEL:
                    raw = ET.tostring(model, encoding="utf-8", xml_declaration=True)
                elif name == MANIFEST:
                    raw = ET.tostring(manifest, encoding="utf-8", xml_declaration=True)
                elif name == SETTINGS:
                    raw = json.dumps(config, separators=(",", ":")).encode()
                else:
                    raw = src.read(name)
                out.writestr(name, raw)
    return output.getvalue()
