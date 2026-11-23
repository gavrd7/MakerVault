"""Strict non-printing modifier admission for pinned Creality 7.3.1 native 3MF.

Creality stores a component parent in the main model and its meshes in a
relationship-linked external submodel. Rebuild a *canonical in-memory* 3MF
from those exact parts and reuse the existing bounded modifier validator.
Never execute embedded settings or trust a vendor project merely because
its model imports successfully.
"""
from copy import deepcopy
import io
import json
import re
import uuid
import zipfile
from defusedxml import ElementTree as SafeET
from xml.etree import ElementTree as ET

from .runner import WorkerError
from .modifier_3mf_validation import (
    validate_modifier_fixture_3mf, NS, IDENTITY, MEMBERS,
)

P = "{http://schemas.microsoft.com/3dmanufacturing/production/2015/06}"
REL = "{http://schemas.openxmlformats.org/package/2006/relationships}"
EXTRA = frozenset({
    "3D/Objects/object_1.model", "3D/_rels/3dmodel.model.rels",
    "Metadata/project_settings.config", "Metadata/creality.config",
})
BLOCKED = frozenset({
    "post_process", "post_process_script", "post_process_scripts",
    "post_processing", "post_processing_script", "post_processing_scripts",
    "upload_host", "upload_url", "print_host", "print_host_webui",
    "printhost_apikey", "printhost_password", "printhost_authorization_type",
    "printer_agent",
})


def _read_xml(archive, name):
    try:
        return SafeET.fromstring(archive.read(name))
    except (SafeET.ParseError, ValueError, TypeError):
        raise WorkerError("Malformed native Creality modifier XML.") from None


def _uuid(value):
    try:
        if not isinstance(value, str) or len(value) > 40:
            raise ValueError()
        uuid.UUID(value)
    except (ValueError, TypeError, AttributeError):
        raise WorkerError("Invalid native Creality modifier object identity.") from None


def _safe_project_settings(node, depth=0):
    if depth > 12:
        raise WorkerError("Creality modifier native settings exceed nesting limit.")
    if isinstance(node, dict):
        if len(node) > 4096:
            raise WorkerError("Oversized native modifier project settings.")
        for key, value in node.items():
            if not isinstance(key, str) or len(key) > 128 or key.lower() in BLOCKED:
                raise WorkerError("Unsafe native modifier project setting.")
            _safe_project_settings(value, depth + 1)
    elif isinstance(node, list):
        if len(node) > 4096:
            raise WorkerError("Oversized native modifier settings vector.")
        for value in node:
            _safe_project_settings(value, depth + 1)
    elif node is not None and not isinstance(node, (str, bool, int, float)):
        raise WorkerError("Invalid native modifier project value.")
    elif isinstance(node, str) and len(node) > 65536:
        raise WorkerError("Oversized native modifier project field.")


def validate_creality_modifier_project(data):
    """Verify exactly the generated 8-member, one-printable-object structure."""
    if not isinstance(data, bytes) or not 0 < len(data) <= 32 * 1024 * 1024:
        raise WorkerError("Invalid Creality modifier upload size.")
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            info = archive.infolist()
            if (len(info) != 8 or {part.filename for part in info} != MEMBERS | EXTRA
                    or any(part.is_dir() or part.file_size <= 0 or
                           part.file_size > (4 * 1024 * 1024 if
                               part.filename in {"Metadata/project_settings.config",
                                                 "Metadata/creality.config"} else
                               80 * 1024 * 1024) for part in info)
                    or sum(part.file_size for part in info) > 96 * 1024 * 1024
                    or archive.getinfo("Metadata/model_settings.config").file_size > 32768
                    or archive.getinfo("3D/_rels/3dmodel.model.rels").file_size > 8192):
                raise WorkerError("Unsafe Creality modifier project archive.")

            main = _read_xml(archive, "3D/3dmodel.model")
            external = _read_xml(archive, "3D/Objects/object_1.model")
            settings = _read_xml(archive, "Metadata/model_settings.config")
            creality = _read_xml(archive, "Metadata/creality.config")
            relations = _read_xml(archive, "3D/_rels/3dmodel.model.rels")
            if creality.tag != "config" or len(creality) != 5:
                raise WorkerError("Invalid Creality modifier project identity.")
            creality_fields = {
                el.get("key"): el.get("value") for el in creality
                if el.tag == "metadata" and not len(el)
                and set(el.attrib) == {"key", "value"}
            }
            if (len(creality_fields) != 5 or creality_fields.get("Application") !=
                    "Creality_Print" or creality_fields.get("AppVersion") != "7.3.1"
                    or creality_fields.get("Company") != "Creality"):
                raise WorkerError("Unapproved Creality modifier project version.")
            if relations.tag != REL + "Relationships" or len(relations) != 1:
                raise WorkerError("Unsafe Creality modifier relationship.")
            relationship = relations[0]
            if relationship.tag != REL + "Relationship" or relationship.attrib != {
                "Target": "/3D/Objects/object_1.model", "Id": "rel-1",
                "Type": "http://schemas.microsoft.com/3dmanufacturing/2013/01/3dmodel"
            }:
                raise WorkerError("Unsupported external modifier mesh relationship.")
            if main.tag != NS + "model" or external.tag != NS + "model":
                raise WorkerError("Invalid Creality native modifier model.")
            if (main.get("unit") != "millimeter" or
                    external.get("unit") != "millimeter"):
                raise WorkerError("Unexpected modifier mesh units.")
            metadata = main.findall(NS + "metadata")
            if len(metadata) != 1 or metadata[0].attrib != {"name": "Application"} or (
                    metadata[0].text or "") != "Creality_Print V7.3.1":
                raise WorkerError("Invalid native Creality model generator.")
            main_resources = main.find(NS + "resources")
            main_build = main.find(NS + "build")
            external_resources = external.find(NS + "resources")
            external_build = external.find(NS + "build")
            if (main_resources is None or main_build is None
                    or external_resources is None or external_build is None
                    or len(main_resources) != 1 or len(main_build) != 1
                    or len(external_build) != 0
                    or len(list(external)) != 2
                    or len(list(main)) != 3):
                raise WorkerError("Invalid native external modifier object graph.")
            parent = main_resources[0]
            if (parent.tag != NS + "object" or
                    parent.get("id") != "2" or
                    parent.get("type") != "model" or
                    set(parent.attrib) != {"id", "type", P + "UUID"} or
                    len(parent) != 1 or parent[0].tag != NS + "components"):
                raise WorkerError("Invalid Creality native modifier parent.")
            _uuid(parent.get(P + "UUID"))
            if (main_build[0].tag != NS + "item"
                    or main_build[0].get("objectid") != "2"
                    or main_build[0].get("transform") != IDENTITY
                    or main_build[0].get("printable") != "1"
                    or set(main_build[0].attrib) != {
                        "objectid", "transform", "printable"
                    }):
                raise WorkerError("Nonprinting modifier may not enter the build.")
            children = list(parent[0])
            meshes = list(external_resources)
            if not 2 <= len(children) == len(meshes) <= 13:
                raise WorkerError("Invalid external modifier mesh count.")
            canonical = ET.Element(NS + "model", {"unit": "millimeter"})
            resources = ET.SubElement(canonical, NS + "resources")
            parent_copy = ET.SubElement(resources, NS + "object",
                                        {"id": "1", "type": "model"})
            comps = ET.SubElement(parent_copy, NS + "components")
            for index, (child, mesh) in enumerate(zip(children, meshes), start=1):
                if (child.tag != NS + "component" or child.attrib != {
                        "objectid": str(index),
                        P + "path": "/3D/Objects/object_1.model",
                        "transform": IDENTITY
                    } or len(child)):
                    raise WorkerError("Unsafe Creality modifier external link.")
                if (mesh.tag != NS + "object" or
                        mesh.get("id") != str(index) or
                        mesh.get("type") != "model" or
                        set(mesh.attrib) != {"id", "type", P + "UUID"}):
                    raise WorkerError("Unsafe external modifier mesh identity.")
                _uuid(mesh.get(P + "UUID"))
                duplicate = deepcopy(mesh)
                duplicate.attrib.clear()
                duplicate.attrib.update({"id": str(index + 1), "type": "model"})
                resources.append(duplicate)
                ET.SubElement(comps, NS + "component", {
                    "objectid": str(index + 1), "transform": IDENTITY})
            build = ET.SubElement(canonical, NS + "build")
            ET.SubElement(build, NS + "item", {
                "objectid": "1", "transform": IDENTITY})

            if settings.tag != "config" or settings.attrib or len(settings) != 2:
                raise WorkerError("Unexpected Creality modifier settings sections.")
            records = settings.findall("object")
            plates = settings.findall("plate")
            if len(records) != 1 or len(plates) != 1:
                raise WorkerError("Creality modifier source object mapping is invalid.")
            record = records[0]
            if record.attrib != {"id": "2"}:
                raise WorkerError("Creality modifier native metadata owner mismatch.")
            clean = ET.Element("config")
            clone = ET.SubElement(clean, "object", {"id": "1"})
            for entry in record:
                if entry.tag == "metadata":
                    if set(entry.attrib) != {"key", "value"}:
                        raise WorkerError("Unsafe native modifier metadata.")
                    if entry.get("key") in {"extruder", "name"}:
                        if entry.get("key") == "extruder" and entry.get("value") != "1":
                            raise WorkerError("Unexpected Creality modifier material tool.")
                        continue
                    clone.append(deepcopy(entry))
                elif entry.tag == "part":
                    clone.append(deepcopy(entry))
                    clone[-1].set("id", str(len(clone.findall("part")) + 1))
                else:
                    raise WorkerError("Unexpected Creality modifier settings entry.")
            if len(clone.findall("part")) != len(children):
                raise WorkerError("Creality modifier part count mismatch.")
            for index, part in enumerate(clone.findall("part"), start=1):
                source_id = int(index)
                if part.attrib.get("id") != str(index + 1) or (
                        part.get("subtype") !=
                        ("normal_part" if index == 1 else "modifier_part")):
                    raise WorkerError("Creality modifier part type mismatch.")
            native_plate = plates[0]
            if native_plate.attrib or native_plate.tag != "plate":
                raise WorkerError("Unsafe Creality modifier plate.")
            new_plate = ET.SubElement(clean, "plate")
            for item in native_plate:
                if item.tag == "metadata":
                    if item.attrib == {"key": "locked", "value": "false"}:
                        continue
                    if item.attrib != {"key": "plater_id", "value": "1"}:
                        raise WorkerError("Unapproved Creality modifier plate setting.")
                    new_plate.append(deepcopy(item))
                elif item.tag == "model_instance":
                    instance = deepcopy(item)
                    for member in instance:
                        if member.tag == "metadata" and member.get("key") == "object_id":
                            if member.get("value") != "2":
                                raise WorkerError("Invalid modifier target plate object.")
                            member.set("value", "1")
                    new_plate.append(instance)
                else:
                    raise WorkerError("Unsafe Creality modifier plate item.")
            model_settings = ET.tostring(clean, encoding="utf-8")
            model_source = ET.tostring(canonical, encoding="utf-8")
            clean_archive = io.BytesIO()
            with zipfile.ZipFile(clean_archive, "w", compression=zipfile.ZIP_DEFLATED,
                                 allowZip64=False) as output:
                output.writestr("3D/3dmodel.model", model_source)
                output.writestr("Metadata/model_settings.config", model_settings)
                output.writestr("_rels/.rels", archive.read("_rels/.rels"))
                output.writestr("[Content_Types].xml",
                                archive.read("[Content_Types].xml"))
            try:
                native = json.loads(archive.read("Metadata/project_settings.config"))
            except (ValueError, UnicodeError):
                raise WorkerError("Invalid native modifier profile vector.") from None
            if (not isinstance(native, dict) or
                    native.get("version") != "7.3.1" or
                    native.get("name") != "project_settings" or
                    native.get("from") != "project"):
                raise WorkerError("Unapproved native modifier process settings.")
            _safe_project_settings(native)
            vectors = native.get("filament_settings_id")
            if (not isinstance(vectors, list) or len(vectors) != 4
                    or any(not isinstance(v, str) or not 0 < len(v) <= 256
                           for v in vectors)):
                raise WorkerError("Invalid Creality modifier native palette.")
        # Reuse the exact bounded non-printing mesh/part/plate validator.
        validate_modifier_fixture_3mf(clean_archive.getvalue())
    except WorkerError:
        raise
    except (zipfile.BadZipFile, OSError, ValueError, TypeError,
            KeyError, SafeET.ParseError, ET.ParseError):
        raise WorkerError("Malformed Creality native modifier archive.") from None
    return True
