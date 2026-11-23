"""Strict, fixture-only admission for one native non-printing modifier project.

Not enabled by the production slicing request path. No vendor scripts,
arbitrary project settings, extra members or executable paths are accepted.
"""
import io
import math
import re
import zipfile
from xml.etree import ElementTree as ET

from .runner import WorkerError


NS = "{http://schemas.microsoft.com/3dmanufacturing/core/2015/02}"
MEMBERS = frozenset({"3D/3dmodel.model", "Metadata/model_settings.config",
                     "_rels/.rels", "[Content_Types].xml"})
IDENTITY = "1 0 0 0 1 0 0 0 1 0 0 0"
IDENTITY4 = "1 0 0 0 0 1 0 0 0 0 1 0 0 0 0 1"
MAX_MODIFIERS = 12


def _metadata(node, *, permitted):
    result = {}
    for entry in node:
        if (entry.tag != "metadata" or set(entry.attrib) != {"key", "value"}
                or len(entry)):
            raise WorkerError("Unsafe native modifier metadata.")
        key, value = entry.attrib["key"], entry.attrib["value"]
        if key not in permitted or key in result:
            raise WorkerError("Unsupported or duplicate native modifier setting.")
        result[key] = value
    return result


def _settings(metadata, *, allow_names=False):
    accepted = {"wall_loops", "sparse_infill_density"}
    if allow_names:
        accepted |= {"name", "matrix"}
    if set(metadata) - accepted:
        raise WorkerError("Unsafe modifier settings.")
    if "name" in metadata and (not 1 <= len(metadata["name"]) <= 120 or
                                any(ord(ch) < 32 for ch in metadata["name"])):
        raise WorkerError("Invalid native modifier part name.")
    if "matrix" in metadata and metadata["matrix"] != IDENTITY4:
        raise WorkerError("Unsafe native modifier part matrix.")
    if "wall_loops" in metadata:
        value = metadata["wall_loops"]
        if not value.isdecimal() or not 0 <= int(value) <= 20:
            raise WorkerError("Invalid regional wall loops.")
    if "sparse_infill_density" in metadata:
        value = metadata["sparse_infill_density"]
        if not re.fullmatch(r"(?:\d{1,3})(?:\.\d{1,3})?%", value):
            raise WorkerError("Invalid regional infill percentage.")
        if not 0 <= float(value[:-1]) <= 100:
            raise WorkerError("Regional infill percentage out of range.")


def _mesh(obj):
    if obj.attrib.get("type") != "model" or set(obj.attrib) != {"id", "type"}:
        raise WorkerError("Unexpected modifier mesh type.")
    if len(obj) != 1 or obj[0].tag != NS + "mesh":
        raise WorkerError("Only regular mesh parts are permitted.")
    mesh = obj[0]
    if len(mesh) != 2 or [child.tag for child in mesh] != [NS + "vertices", NS + "triangles"]:
        raise WorkerError("Invalid native modifier triangle mesh.")
    verts, faces = mesh
    if not 4 <= len(verts) <= 500000 or not 4 <= len(faces) <= 500000:
        raise WorkerError("Modifier geometry exceeds mesh limits.")
    for vertex in verts:
        if vertex.tag != NS + "vertex" or set(vertex.attrib) != {"x", "y", "z"} or len(vertex):
            raise WorkerError("Unexpected modifier vertex.")
        try:
            numbers = [float(vertex.attrib[k]) for k in ("x", "y", "z")]
        except ValueError:
            raise WorkerError("Invalid modifier vertex.") from None
        if any(not math.isfinite(v) or abs(v) > 20000 for v in numbers):
            raise WorkerError("Unsafe modifier vertex coordinates.")
    for face in faces:
        if face.tag != NS + "triangle" or set(face.attrib) != {"v1", "v2", "v3"} or len(face):
            raise WorkerError("Unsafe modifier triangle.")
        for name in ("v1", "v2", "v3"):
            value = face.attrib[name]
            if not value.isdecimal() or int(value) >= len(verts):
                raise WorkerError("Invalid native modifier triangle index.")
    return len(faces)


def validate_modifier_fixture_3mf(data):
    """Validate precisely one composed parent with 1-12 non-printing children."""
    if not isinstance(data, bytes) or not 0 < len(data) <= 32 * 1024 * 1024:
        raise WorkerError("Native modifier fixture exceeds upload limits.")
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as package:
            info = package.infolist()
            if (len(info) != 4 or {part.filename for part in info} != MEMBERS
                    or any(part.is_dir() or part.file_size <= 0
                           or part.file_size > 80 * 1024 * 1024 for part in info)
                    or sum(part.file_size for part in info) > 96 * 1024 * 1024
                    or package.getinfo("Metadata/model_settings.config").file_size > 32768):
                raise WorkerError("Unsafe native modifier fixture members.")
            root = ET.fromstring(package.read("3D/3dmodel.model"))
            manifest = ET.fromstring(package.read("Metadata/model_settings.config"))
    except WorkerError:
        raise
    except (zipfile.BadZipFile, ET.ParseError, OSError, ValueError):
        raise WorkerError("Invalid native modifier fixture.") from None
    if root.tag != NS + "model" or root.attrib.get("unit") != "millimeter":
        raise WorkerError("Invalid native modifier model namespace.")
    resources = root.find(NS + "resources")
    build = root.find(NS + "build")
    if resources is None or build is None or len(root) != 2 or len(build) != 1:
        raise WorkerError("Native modifier fixture must have exactly one build item.")
    objs = list(resources)
    if not 3 <= len(objs) <= MAX_MODIFIERS + 2:
        raise WorkerError("Native modifier fixture must contain one base and modifiers.")
    ids = [obj.attrib.get("id") for obj in objs]
    if ids != [str(i) for i in range(1, len(objs) + 1)]:
        raise WorkerError("Unexpected native modifier resource IDs.")
    parent = objs[0]
    if (parent.attrib != {"id": "1", "type": "model"}
            or len(parent) != 1 or parent[0].tag != NS + "components"):
        raise WorkerError("Native modifier parent must contain components, not an STL mesh.")
    components = parent[0]
    expected = [str(i) for i in range(2, len(objs) + 1)]
    if (len(components) != len(expected)
            or [c.attrib.get("objectid") for c in components] != expected
            or any(c.tag != NS + "component" or
                   c.attrib != {"objectid": expected[i], "transform": IDENTITY}
                   or len(c) for i, c in enumerate(components))):
        raise WorkerError("Native modifier child component identity is invalid.")
    if build[0].tag != NS + "item" or build[0].attrib != {
        "objectid": "1", "transform": IDENTITY
    } or len(build[0]):
        raise WorkerError("Modifier mesh must not be a printable build item.")
    count = sum(_mesh(obj) for obj in objs[1:])
    if count > 500000:
        raise WorkerError("Native modifier triangle budget exceeded.")
    if manifest.tag != "config" or manifest.attrib or len(manifest) != 2:
        raise WorkerError("Unsafe modifier plate manifest.")
    native, plate = manifest
    if native.tag != "object" or native.attrib != {"id": "1"}:
        raise WorkerError("Modifier parts must belong to the built parent.")
    parts = [n for n in native if n.tag == "part"]
    parent_meta = [n for n in native if n.tag == "metadata"]
    if len(parent_meta) + len(parts) != len(native) or len(parts) != len(expected):
        raise WorkerError("Invalid native modifier part mapping.")
    _settings(_metadata_list(parent_meta, {"wall_loops", "sparse_infill_density"}))
    for number, part in enumerate(parts):
        expected_id = expected[number]
        subtype = "normal_part" if number == 0 else "modifier_part"
        if part.attrib != {"id": expected_id, "subtype": subtype}:
            raise WorkerError("Native modifier part type or identity mismatch.")
        settings = _metadata(part, permitted={
            "name", "matrix", "wall_loops", "sparse_infill_density"})
        _settings(settings, allow_names=True)
        if "name" not in settings or settings.get("matrix") != IDENTITY4:
            raise WorkerError("Native modifier part identity metadata missing.")
        if number > 0 and not (set(settings) & {"wall_loops", "sparse_infill_density"}):
            raise WorkerError("Modifier part has no validated regional settings.")
    if plate.tag != "plate" or plate.attrib or len(plate) != 2:
        raise WorkerError("Modifier project must contain one native plate mapping.")
    marker, instance = plate
    if (marker.tag != "metadata" or marker.attrib != {"key": "plater_id", "value": "1"}
            or instance.tag != "model_instance" or instance.attrib or len(instance) != 3
            or _metadata(instance, permitted={"object_id", "instance_id", "identify_id"}) != {
                "object_id": "1", "instance_id": "0", "identify_id": "1"
            }):
        raise WorkerError("Unsafe modifier native plate membership.")
    return True


def _metadata_list(nodes, permitted):
    temporary = ET.Element("metadata_group")
    temporary.extend(nodes)
    return _metadata(temporary, permitted=permitted)
