"""Privacy-safe structural comparison of MakerVault and native Creality 3MFs.

Never executes a reference project. Reports only schema differences, counts,
file roles, option *key names* and value types; never profile values, project
filenames, object names, paths, scripts, colours, or geometry coordinates.
"""
import io
import json
import re
import zipfile
from defusedxml import ElementTree as ET

MAX_ARCHIVE = 64 * 1024 * 1024
MAX_UNPACKED = 160 * 1024 * 1024
MAX_MEMBER = 80 * 1024 * 1024
OPTION_KEY = re.compile(r"^[a-z][a-z0-9_]{0,79}$")
MODEL_NS = "{http://schemas.microsoft.com/3dmanufacturing/core/2015/02}"
SETTINGS = "Metadata/project_settings.config"


def _safe_xml(raw):
    return ET.fromstring(raw)


def _shape(value):
    if isinstance(value, list):
        if not value:
            return "list:0"
        types = sorted(set(_shape(v).split(":")[0] for v in value))
        return "list:%d:%s" % (len(value), ",".join(types[:4]))
    if isinstance(value, dict):
        return "object"
    if isinstance(value, bool):
        return "bool"
    if value is None:
        return "null"
    if isinstance(value, str):
        return "str"
    if isinstance(value, (float, int)):
        return "number"
    return "other"


def _role(name):
    if name == SETTINGS:
        return "project-settings"
    if name == "Metadata/model_settings.config":
        return "model-settings"
    if name == "Metadata/creality.config":
        return "creality-metadata"
    if name == "[Content_Types].xml":
        return "content-types"
    if name.endswith(".rels"):
        return "relationships"
    if name.startswith("3D/") and name.endswith(".model"):
        return "3d-model"
    if name.startswith("3D/") and name.endswith(".xml"):
        return "3d-xml"
    if name.startswith("Metadata/"):
        return "other-metadata"
    return "other-member"


def _structure(data):
    if not isinstance(data, bytes) or not 0 < len(data) <= MAX_ARCHIVE:
        raise ValueError("Reference project is outside allowed archive size.")
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        items = z.infolist()
        if (not 1 <= len(items) <= 128
                or len({item.filename for item in items}) != len(items)
                or sum(item.file_size for item in items) > MAX_UNPACKED
                or any(item.file_size > MAX_MEMBER or item.is_dir() for item in items)):
            raise ValueError("Unsafe or oversized 3MF archive structure.")
        by_role = {}
        for item in items:
            role = _role(item.filename)
            by_role[role] = by_role.get(role, 0) + 1
        config = json.loads(z.read(SETTINGS))
        if not isinstance(config, dict) or len(config) > 4096:
            raise ValueError("Invalid 3MF project settings.")
        schema = {key: _shape(value) for key, value in config.items()
                  if isinstance(key, str) and OPTION_KEY.fullmatch(key)}
        count = {"resource_objects": 0, "meshes": 0, "component_groups": 0,
                 "component_links": 0, "build_items": 0, "model_documents": 0,
                 "object_records": 0, "part_records": 0, "plates": 0,
                 "model_instances": 0, "assembly_items": 0,
                 "relationships": 0}
        for item in items:
            name = item.filename
            if _role(name) == "3d-model":
                root = _safe_xml(z.read(name))
                if root.tag != MODEL_NS + "model":
                    continue
                count["model_documents"] += 1
                objects = root.findall("./" + MODEL_NS + "resources/" + MODEL_NS + "object")
                count["resource_objects"] += len(objects)
                for obj in objects:
                    if obj.find(MODEL_NS + "mesh") is not None:
                        count["meshes"] += 1
                    components = obj.find(MODEL_NS + "components")
                    if components is not None:
                        count["component_groups"] += 1
                        count["component_links"] += len(components)
                count["build_items"] += len(root.findall("./" + MODEL_NS + "build/" + MODEL_NS + "item"))
            elif name == "Metadata/model_settings.config":
                root = _safe_xml(z.read(name))
                count["object_records"] += len(root.findall("object"))
                count["part_records"] += len(root.findall("./object/part"))
                count["plates"] += len(root.findall("plate"))
                count["model_instances"] += len(root.findall("./plate/model_instance"))
                count["assembly_items"] += len(root.findall("./assemble/assemble_item"))
            elif _role(name) == "relationships":
                root = _safe_xml(z.read(name))
                count["relationships"] += sum(child.tag.endswith("Relationship") for child in root)
        return {"member_roles": by_role, "counts": count, "settings": schema}


def compare_projects(candidate, reference):
    left = _structure(candidate)
    right = _structure(reference)
    common = sorted(left["settings"].keys() & right["settings"].keys())
    # Preserve native option NAMES only. Never log field values.
    missing = sorted(right["settings"].keys() - left["settings"].keys())
    extra = sorted(left["settings"].keys() - right["settings"].keys())
    mismatched = [name for name in common
                  if left["settings"][name] != right["settings"][name]]
    return {
        "reference_version_note": "Reference may have been exported by a different Creality 7.3.x patch release.",
        "candidate_setting_count": len(left["settings"]),
        "reference_setting_count": len(right["settings"]),
        "missing_setting_keys": missing[:120],
        "missing_setting_count": len(missing),
        "extra_setting_keys": extra[:120],
        "extra_setting_count": len(extra),
        "different_value_shapes": [{
            "key": name, "candidate": left["settings"][name],
            "reference": right["settings"][name],
        } for name in mismatched[:120]],
        "different_value_shape_count": len(mismatched),
        "candidate_archive_roles": left["member_roles"],
        "reference_archive_roles": right["member_roles"],
        "candidate_structure_counts": left["counts"],
        "reference_structure_counts": right["counts"],
    }
