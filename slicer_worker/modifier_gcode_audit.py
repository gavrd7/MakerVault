"""Bounded positive-E coverage check for verified native parameter modifiers.

The pin/version tests separately prove that changing a regional setting changes
real G-code. This per-job safety check ensures every requested modifier actually
overlaps deposited model paths; it does not claim independent print fidelity.
"""
import io
import math
import re
import zipfile
from defusedxml import ElementTree as SafeET

from .runner import WorkerError
from .modifier_3mf_validation import NS

CMD = re.compile(r"^(G0?[01]|G92|M82|M83|G90|G91)\b", re.I)
WORDS = re.compile(r"\b([XYZE])([-+]?(?:\d+(?:\.\d*)?|\.\d+))", re.I)


def modifier_bounds(project, engine):
    if not isinstance(project, bytes) or len(project) > 32 * 1024 * 1024:
        raise WorkerError("Invalid modifier geometry for G-code audit.")
    try:
        with zipfile.ZipFile(io.BytesIO(project)) as archive:
            if engine == "crealityprint":
                source = archive.read("3D/Objects/object_1.model")
                start = 1
            else:
                source = archive.read("3D/3dmodel.model")
                start = 2
            root = SafeET.fromstring(source)
        objects = root.findall(NS + "resources/" + NS + "object")
        if not 2 <= len(objects) - start + 1 <= 13:
            raise WorkerError("Missing bounded modifier part coordinates.")
        bounds = []
        for obj in objects[start:]:
            vertices = obj.findall(NS + "mesh/" + NS + "vertices/" + NS + "vertex")
            if not 4 <= len(vertices) <= 500000:
                raise WorkerError("Invalid modifier mesh bounds.")
            points = []
            for point in vertices:
                coords = tuple(float(point.attrib[axis]) for axis in ("x", "y", "z"))
                if any(not math.isfinite(v) or abs(v) > 20000 for v in coords):
                    raise WorkerError("Invalid native modifier coordinate.")
                points.append(coords)
            bounds.append(tuple((min(v[i] for v in points), max(v[i] for v in points))
                                for i in range(3)))
        if not bounds:
            raise WorkerError("No modifier regions available for G-code audit.")
        return bounds
    except WorkerError:
        raise
    except (KeyError, ValueError, OSError, zipfile.BadZipFile,
            SafeET.ParseError, TypeError, AttributeError):
        raise WorkerError("Unable to audit native modifier geometry.") from None


def audit_modifier_positive_e(gcode, project, engine):
    """Require model deposition inside each non-printing modifier's 3D bbox."""
    if not isinstance(gcode, bytes) or not 0 < len(gcode) <= 64 * 1024 * 1024:
        raise WorkerError("Invalid modifier G-code output.")
    boxes = modifier_bounds(project, engine)
    x = y = z = e = 0.0
    relative_xyz = relative_e = False
    hits = [0] * len(boxes)
    deposited = 0
    for raw in gcode.decode("utf-8", "replace").splitlines():
        command = raw.partition(";")[0].strip().upper()
        matched = CMD.match(command)
        if not matched:
            continue
        opcode = matched.group(1)
        if opcode == "G90":
            relative_xyz = False
            continue
        if opcode == "G91":
            relative_xyz = True
            continue
        if opcode in ("M82", "M83"):
            relative_e = opcode == "M83"
            continue
        fields = {axis: float(value) for axis, value in WORDS.findall(command)}
        if any(not math.isfinite(v) for v in fields.values()):
            raise WorkerError("Non-finite native modifier G-code coordinate.")
        if opcode == "G92":
            x, y, z, e = (fields.get("X", x), fields.get("Y", y),
                           fields.get("Z", z), fields.get("E", e))
            continue
        nx = x + fields["X"] if relative_xyz and "X" in fields else fields.get("X", x)
        ny = y + fields["Y"] if relative_xyz and "Y" in fields else fields.get("Y", y)
        nz = z + fields["Z"] if relative_xyz and "Z" in fields else fields.get("Z", z)
        extrusion = 0.0
        if "E" in fields:
            extrusion = fields["E"] if relative_e else fields["E"] - e
            if not relative_e:
                e = fields["E"]
        if opcode in ("G1", "G01") and extrusion > 0 and (nx != x or ny != y):
            deposited += 1
            midpoint = ((nx + x) / 2, (ny + y) / 2, nz)
            for i, box in enumerate(boxes):
                if all(low - 0.05 <= value <= high + 0.05
                       for (low, high), value in zip(box, midpoint)):
                    hits[i] += 1
        x, y, z = nx, ny, nz
    if deposited < 10 or any(count == 0 for count in hits):
        raise WorkerError("Requested native modifier has no model deposition in the generated G-code.")
    return {"modifier_count": len(boxes), "positive_e_paths": deposited,
            "modifier_region_paths": hits}
