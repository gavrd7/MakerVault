"""Verify a Creality self-contained native 3MF project without trusting ZIP metadata.

The core model and per-object tool metadata use the existing restricted
MakerVault 3MF validator. Embedded project config is allowlisted separately
and is never interpreted as an executable command.
"""
import io
import json
import zipfile
from xml.etree import ElementTree as ET

from .runner import WorkerError
from .resource_budget import model_input_budget, operation_memory_budget
from .three_mf_validation import validate_worker_3mf

PROJECT_SETTINGS = "Metadata/project_settings.config"
CREALITY_META = "Metadata/creality.config"
LAYER_RANGES = "Metadata/layer_config_ranges.xml"
CORE_MEMBERS = {"3D/3dmodel.model", "Metadata/model_settings.config",
                "[Content_Types].xml", "_rels/.rels"}
BLOCKED = {"post_process", "post_process_script", "post_process_scripts",
           "post_processing_script", "upload_host", "upload_url",
           "print_host", "print_host_webui", "printhost_apikey"}


def validate_creality_project(data, *, native_tool_count=2):
    if not isinstance(data, bytes) or len(data) > model_input_budget():
        raise WorkerError("Invalid Creality native project size.")
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            parts = archive.infolist()
            if (len(parts) not in (6, 7) or set(p.filename for p in parts) not in (
                    CORE_MEMBERS | {PROJECT_SETTINGS, CREALITY_META},
                    CORE_MEMBERS | {PROJECT_SETTINGS, CREALITY_META, LAYER_RANGES}) or
                    any(p.is_dir() or p.file_size <= 0 or
                        p.file_size > (32768 if p.filename == LAYER_RANGES else
                                       4 * 1024 * 1024 if p.filename in (PROJECT_SETTINGS, CREALITY_META)
                                       else (operation_memory_budget(reserve_bytes=256 * 1024 * 1024, expansion_factor=12) or 80 * 1024 * 1024)) for p in parts) or
                    sum(p.file_size for p in parts) > (operation_memory_budget(reserve_bytes=256 * 1024 * 1024, expansion_factor=10) or 96 * 1024 * 1024)):
                raise WorkerError("Creality native project contains unsupported content.")
            xml = ET.fromstring(archive.read(CREALITY_META))
            if xml.tag != "config":
                raise WorkerError("Invalid Creality native project identification.")
            identity = {row.attrib.get("key"): row.attrib.get("value")
                        for row in xml if row.tag == "metadata" and not len(row)}
            if (identity.get("Application") != "Creality_Print" or
                    not identity.get("AppVersion", "").startswith("7.3.")):
                raise WorkerError("Unrecognised native Creality 3MF identity.")
            # CLI 7.3.x takes the project file version from the model
            # Application metadata, not only from creality.config.
            import re
            model_root = ET.fromstring(archive.read("3D/3dmodel.model"))
            ns = "{http://schemas.microsoft.com/3dmanufacturing/core/2015/02}"
            if model_root.tag != ns + "model":
                raise WorkerError("Unrecognised native Creality model root.")
            # A colour-painted single model has two *filaments*, not two
            # separate printable objects. The strict lower-level validator
            # still requires extrusion tools 0 and 1 to be represented by
            # actual per-triangle native paint selectors.
            object_count = len(model_root.findall(
                "./" + ns + "resources/" + ns + "object"))
            if object_count not in (1, 2):
                raise WorkerError("Creality CFS project needs one painted or two plain objects.")
            generator = [
                entry.text or "" for entry in model_root.findall(ns + "metadata")
                if entry.get("name") == "Application"
            ]
            if len(generator) != 1 or not re.fullmatch(
                    r"Creality_Print V7\.3\.[0-9]+", generator[0]):
                raise WorkerError("Creality project model generator version is missing or incompatible.")
            project = json.loads(archive.read(PROJECT_SETTINGS))
            if (not isinstance(project, dict) or len(project) > 4096 or
                    project.get("name") != "project_settings" or
                    project.get("from") != "project" or
                    not isinstance(project.get("version"), str) or
                    not project["version"].startswith("7.3.")):
                raise WorkerError("Creality native project settings are invalid.")
            if any(key.lower() in BLOCKED for key in project):
                raise WorkerError("Creality native project contains blocked settings.")
            names = project.get("filament_settings_id")
            if not isinstance(names, list) or len(names) not in (native_tool_count, 4) or any(
                    not isinstance(name, str) or not 0 < len(name) <= 256 for name in names):
                raise WorkerError("Creality native project filament palette is incomplete.")
            # A four-bay K2 palette may have only two model-assigned tools.
            # Vector and flushing dimensions must stay coherent.
            slots = len(names)
            for key in ("filament_map", "filament_map_2", "filament_colour_type",
                        "filament_volume_map", "filament_nozzle_variant"):
                value = project.get(key)
                if value is not None and (not isinstance(value, list) or len(value) != slots):
                    raise WorkerError("Creality filament palette vector size is invalid.")
            for key, length in (("flush_volumes_matrix", slots * slots),
                                ("flush_volumes_vector", 2 * slots)):
                value = project.get(key)
                if value is not None and (not isinstance(value, list) or len(value) != length):
                    raise WorkerError("Creality purge matrix dimensions are invalid.")
            # Validate native model settings safely, then construct a stripped
            # manifest for the existing, strict worker geometry verifier.
            settings_root = ET.fromstring(archive.read("Metadata/model_settings.config"))
            records = settings_root.findall("object")
            plates = settings_root.findall("plate")
            assemblies = settings_root.findall("assemble")
            if (settings_root.tag != "config" or len(records) != object_count
                    or len(plates) != 1 or len(assemblies) > 1):
                raise WorkerError("Creality native object metadata is inconsistent.")
            clean = ET.Element("config")
            for record in records:
                if record.tag != "object" or set(record.attrib) != {"id"}:
                    raise WorkerError("Unexpected Creality object identity.")
                clone = ET.SubElement(clean, "object", dict(record.attrib))
                values = [row for row in record.findall("metadata")
                          if row.get("key") == "extruder"]
                if len(values) != 1:
                    raise WorkerError("Missing Creality object material assignment.")
                ET.SubElement(clone, "metadata", dict(values[0].attrib))
                parts = record.findall("part")
                if len(parts) > 1 or (parts and
                        (parts[0].get("subtype") != "normal_part" or
                         parts[0].get("id") != "1")):
                    raise WorkerError("Unexpected Creality model-part settings.")
                if parts and any(row.get("key") not in ("name", "matrix")
                                 for row in parts[0].findall("metadata")):
                    raise WorkerError("Unsupported native model-part metadata.")
            plate = plates[0]
            clean_plate = ET.SubElement(clean, "plate")
            for row in plate:
                if row.tag == "metadata":
                    if row.get("key") == "plater_id":
                        ET.SubElement(clean_plate, "metadata", dict(row.attrib))
                elif row.tag == "model_instance":
                    clean_plate.append(row)
                else:
                    raise WorkerError("Unsupported Creality plate metadata.")
            if assemblies:
                if len(assemblies[0]) != object_count:
                    raise WorkerError("Creality assembly instances are inconsistent.")
                for item in assemblies[0]:
                    if (item.tag != "assemble_item" or
                            item.get("transform") != "1 0 0 0 1 0 0 0 1 0 0 0" or
                            item.get("offset") != "0 0 0"):
                        raise WorkerError("Creality assembly would modify the prepared positions.")
            # Validate the restrictive core plate using the existing worker
            # validator, not the project's richer vendor parser.
            core = io.BytesIO()
            with zipfile.ZipFile(core, "w", compression=zipfile.ZIP_DEFLATED,
                                 allowZip64=False) as trimmed:
                for name in sorted(CORE_MEMBERS | ({LAYER_RANGES} if LAYER_RANGES in archive.namelist() else set())):
                    trimmed.writestr(name, ET.tostring(clean, encoding="utf-8")
                                     if name == "Metadata/model_settings.config"
                                     else archive.read(name))
        validate_worker_3mf(
            core.getvalue(), native_tool_count=native_tool_count,
            # Painting extensions require a SINGLE object. The plain
            # two-object/two-tool fixture must use strict per-object
            # assignments, not the combined-paint single-mesh validator.
            allow_creality_combined_paint=object_count == 1,
            allow_creality_layer_ranges=LAYER_RANGES in archive.namelist(),
        )
    except WorkerError:
        raise
    except (ValueError, KeyError, TypeError, OSError, zipfile.BadZipFile,
            UnicodeDecodeError, ET.ParseError):
        raise WorkerError("Malformed Creality native project.") from None
    return True
