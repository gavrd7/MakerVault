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


def validate_worker_3mf(data):
    if not isinstance(data, bytes) or not data or len(data) > 32 * 1024 * 1024:
        raise WorkerError("3MF input exceeds worker limits.")
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as package:
            info = package.infolist()
            if len(info) != 3 or {part.filename for part in info} != ALLOWED:
                raise WorkerError("Unsupported 3MF package members.")
            if any(part.file_size <= 0 or part.file_size > 80 * 1024 * 1024
                   or part.is_dir() for part in info):
                raise WorkerError("3MF package contents are not bounded.")
            if sum(part.file_size for part in info) > 96 * 1024 * 1024:
                raise WorkerError("3MF archive expansion exceeds the limit.")
            raw = package.read("3D/3dmodel.model")
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
        if count > 150000:
            raise WorkerError("3MF triangle count exceeds worker limit.")
        if len(vertices) > 450000:
            raise WorkerError("3MF vertex count exceeds worker limit.")
        for vertex in vertices:
            try:
                values = [float(vertex.attrib[key]) for key in ("x", "y", "z")]
            except (KeyError, ValueError):
                raise WorkerError("3MF vertex coordinates are invalid.") from None
            if any(not math.isfinite(value) or abs(value) > 10000 for value in values):
                raise WorkerError("3MF contains unsafe geometry.")
    for item in items:
        try:
            values = [float(v) for v in item.attrib["transform"].split()]
        except (KeyError, ValueError):
            raise WorkerError("3MF transform is missing or invalid.") from None
        if len(values) != 12 or any(not math.isfinite(v) or abs(v) > 10000 for v in values):
            raise WorkerError("3MF transform is unsafe.")
    return True
