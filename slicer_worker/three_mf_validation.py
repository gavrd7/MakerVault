"""Only accept bounded core 3MF plate packages produced by MakerVault.

No arbitrary vendor projects, scripts, remote relationships or extra archive
members are permitted through this execution path.
"""
import io
import math
import zipfile
from xml.etree import ElementTree as ET

from .runner import WorkerError

CORE_NS = "http://schemas.microsoft.com/3dmanufacturing/core/2015/02"
ALLOWED = {"3D/3dmodel.model", "_rels/.rels", "[Content_Types].xml"}
PLATE_MANIFEST = "Metadata/model_settings.config"
# Keep the worker aligned with the validated STL and server-side 3MF builder.
# Expanded XML, compressed archive and model upload bounds remain separate.
MAX_TRIANGLES = 500_000
MAX_VERTICES_PER_OBJECT = 1_500_000


def validate_worker_3mf(data):
    if not isinstance(data, bytes) or not data or len(data) > 32 * 1024 * 1024:
        raise WorkerError("3MF input exceeds worker limits.")
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as package:
            info = package.infolist()
            names = {part.filename for part in info}
            if len(info) not in (3, 4) or names not in (ALLOWED, ALLOWED | {PLATE_MANIFEST}):
                raise WorkerError("Unsupported 3MF package members.")
            if PLATE_MANIFEST in names and package.getinfo(PLATE_MANIFEST).file_size > 8192:
                raise WorkerError("3MF plate metadata is oversized.")
            if any(part.file_size <= 0 or part.file_size > 80 * 1024 * 1024
                   or part.is_dir() for part in info):
                raise WorkerError("3MF package contents are not bounded.")
            if sum(part.file_size for part in info) > 96 * 1024 * 1024:
                raise WorkerError("3MF archive expansion exceeds the limit.")
            raw = package.read("3D/3dmodel.model")
            manifest = package.read(PLATE_MANIFEST) if PLATE_MANIFEST in names else None
        root = ET.fromstring(raw)
    except WorkerError:
        raise
    except (ValueError, zipfile.BadZipFile, ET.ParseError, OSError):
        raise WorkerError("Invalid 3MF project geometry.") from None
    if root.tag != "{%s}model" % CORE_NS:
        raise WorkerError("Unexpected 3MF namespace.")
    objects = root.findall("./{%s}resources/{%s}object" % (CORE_NS, CORE_NS))
    items = root.findall("./{%s}build/{%s}item" % (CORE_NS, CORE_NS))
    if not 1 <= len(objects) <= 12 or len(items) != len(objects):
        raise WorkerError("3MF build must contain one to twelve objects.")
    ids = {obj.attrib.get("id") for obj in objects}
    if len(ids) != len(objects) or any(item.attrib.get("objectid") not in ids for item in items):
        raise WorkerError("3MF build references unknown objects.")
    count = 0
    for obj in objects:
        vertices = obj.findall("./{%s}mesh/{%s}vertices/{%s}vertex" % (CORE_NS, CORE_NS, CORE_NS))
        triangles = obj.findall("./{%s}mesh/{%s}triangles/{%s}triangle" % (CORE_NS, CORE_NS, CORE_NS))
        if not vertices or not triangles:
            raise WorkerError("3MF build contains empty objects.")
        count += len(triangles)
        if count > MAX_TRIANGLES:
            raise WorkerError("3MF triangle count exceeds worker limit.")
        if len(vertices) > MAX_VERTICES_PER_OBJECT:
            raise WorkerError("3MF vertex count exceeds worker limit.")
        for vertex in vertices:
            try:
                values = [float(vertex.attrib[key]) for key in ("x", "y", "z")]
            except (KeyError, ValueError):
                raise WorkerError("3MF vertex coordinates are invalid.") from None
            if any(not math.isfinite(value) or abs(value) > 10000 for value in values):
                raise WorkerError("3MF contains unsafe geometry.")
    # A standard core 3MF can list many build items without telling native
    # Orca/Creality Print which print plate each item belongs to. For multiple
    # objects, require the minimal manifest emitted by MakerVault's builder.
    if len(items) > 1:
        if manifest is None:
            raise WorkerError("Multi-object 3MF requires explicit native plate membership.")
        try:
            manifest_root = ET.fromstring(manifest)
        except ET.ParseError:
            raise WorkerError("Malformed native 3MF plate manifest.") from None
        if manifest_root.tag != "config" or manifest_root.attrib or len(manifest_root) != 1:
            raise WorkerError("Unsupported native 3MF plate manifest.")
        plate = manifest_root[0]
        if plate.tag != "plate" or plate.attrib or len(plate) != len(items) + 1:
            raise WorkerError("Unexpected 3MF plate mapping.")
        marker = plate[0]
        if (marker.tag != "metadata" or marker.attrib != {"key": "plater_id", "value": "1"}
                or len(marker)):
            raise WorkerError("3MF does not target exactly one plate.")
        instance_ids = []
        for entry in plate[1:]:
            if entry.tag != "model_instance" or entry.attrib or len(entry) != 3:
                raise WorkerError("Invalid 3MF native plate instance.")
            props = {}
            for child in entry:
                if (child.tag != "metadata" or len(child) or set(child.attrib) != {"key", "value"}
                        or child.attrib["key"] in props):
                    raise WorkerError("Unsafe 3MF plate metadata.")
                props[child.attrib["key"]] = child.attrib["value"]
            if (set(props) != {"object_id", "instance_id", "identify_id"}
                    or props["instance_id"] != "0"
                    or props["identify_id"] != props["object_id"]):
                raise WorkerError("Invalid native plate instance identity.")
            instance_ids.append(props["object_id"])
        if len(instance_ids) != len(set(instance_ids)) or set(instance_ids) != ids:
            raise WorkerError("3MF plate membership does not match mesh objects.")
    elif manifest is not None:
        raise WorkerError("Single-object 3MF must not contain an extra native plate manifest.")
    for item in items:
        try:
            values = [float(v) for v in item.attrib["transform"].split()]
        except (KeyError, ValueError):
            raise WorkerError("3MF transform is missing or invalid.") from None
        if len(values) != 12 or any(not math.isfinite(v) or abs(v) > 10000 for v in values):
            raise WorkerError("3MF transform is unsafe.")
    return True
