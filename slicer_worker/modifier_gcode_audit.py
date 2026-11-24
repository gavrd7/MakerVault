"""Bounded positive-E coverage and subtraction checks for native plate volumes.

The pin/version tests separately prove that changing a regional setting changes
real G-code. This per-job safety check ensures every requested modifier actually
overlaps deposited model paths; it does not claim independent print fidelity.
"""
import io
from functools import lru_cache
import math
import re
import zipfile
from xml.etree import ElementTree as SafeET

from .runner import WorkerError
from .modifier_3mf_validation import NS

CMD = re.compile(r"^(G0?[01]|G92|M82|M83|G90|G91)\b", re.I)
WORDS = re.compile(r"\b([XYZE])([-+]?(?:\d+(?:\.\d*)?|\.\d+))", re.I)


def modifier_bounds(project, engine, *, include_kinds=False, include_meshes=False):
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
            if b"<!DOCTYPE" in source.upper() or b"<!ENTITY" in source.upper():
                raise WorkerError("Unsafe modifier geometry XML declaration.")
            root = SafeET.fromstring(source)
        objects = root.findall(NS + "resources/" + NS + "object")
        # Derive non-printing part identities from native settings instead
        # of assuming that every mesh after the first belongs to a modifier.
        # Compound plates can contain several normal printable mesh parts.
        with zipfile.ZipFile(io.BytesIO(project)) as archive:
            settings_source = archive.read("Metadata/model_settings.config")
        if b"<!DOCTYPE" in settings_source.upper() or b"<!ENTITY" in settings_source.upper():
            raise WorkerError("Unsafe native modifier metadata declaration.")
        manifest = SafeET.fromstring(settings_source)
        native_objects = manifest.findall("object")
        if len(native_objects) != 1:
            raise WorkerError("Unexpected native region metadata records.")
        parts = native_objects[0].findall("part")
        expected_count = len(objects) - (0 if engine == "crealityprint" else 1)
        if not 2 <= len(parts) == expected_count <= 60:
            raise WorkerError("Missing bounded native region part coordinates.")
        bounds = []
        kinds = []
        meshes = []
        for part in parts:
            subtype = part.get("subtype")
            if subtype == "normal_part":
                continue
            if subtype not in ("modifier_part", "negative_part"):
                raise WorkerError("Unknown native non-printing subtype.")
            identifier = part.get("id")
            try:
                object_index = int(identifier) - 1
            except (TypeError, ValueError):
                raise WorkerError("Invalid native region object identity.") from None
            if not (0 if engine == "crealityprint" else 1) <= object_index < len(objects):
                raise WorkerError("Invalid native region mesh mapping.")
            obj = objects[object_index]
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
            kinds.append(subtype)
            if include_meshes:
                faces = obj.findall(NS + "mesh/" + NS + "triangles/" + NS + "triangle")
                if not 4 <= len(faces) <= 500000:
                    raise WorkerError("Invalid native region triangle count.")
                triangles = []
                for face in faces:
                    indices = tuple(int(face.attrib[key]) for key in ("v1", "v2", "v3"))
                    if any(index < 0 or index >= len(points) for index in indices):
                        raise WorkerError("Invalid native region triangle index.")
                    triangles.append(tuple(points[index] for index in indices))
                meshes.append(tuple(triangles))
        if not bounds:
            raise WorkerError("No modifier regions available for G-code audit.")
        if include_meshes:
            return bounds, kinds, meshes
        return (bounds, kinds) if include_kinds else bounds
    except WorkerError:
        raise
    except (KeyError, ValueError, OSError, zipfile.BadZipFile,
            SafeET.ParseError, TypeError, AttributeError):
        raise WorkerError("Unable to audit native modifier geometry.") from None


def _section_edges(triangles, z):
    """Intersect the actual triangulated volume with a horizontal plane.

    Half-open edge crossings avoid counting shared triangle vertices twice.
    The tiny upward perturbation resolves planes coincident with mesh faces.
    A torus may yield multiple loops: the even/odd test preserves its hole.
    """
    z += 1e-7
    edges = []
    for triangle in triangles:
        points = []
        for a, b in zip(triangle, triangle[1:] + triangle[:1]):
            if (a[2] <= z < b[2]) or (b[2] <= z < a[2]):
                t = (z - a[2]) / (b[2] - a[2])
                points.append((a[0] + t * (b[0] - a[0]),
                               a[1] + t * (b[1] - a[1])))
        if len(points) == 2 and points[0] != points[1]:
            edges.append(tuple(points))
    return tuple(edges)


def _inside_section(x, y, edges, tolerance=0.15):
    """True only for a point in the section, away from its real contour."""
    inside = False
    for (ax, ay), (bx, by) in edges:
        dx, dy = bx - ax, by - ay
        length_sq = dx * dx + dy * dy
        if length_sq:
            t = max(0., min(1., ((x - ax) * dx + (y - ay) * dy) / length_sq))
            if (x - ax - t * dx) ** 2 + (y - ay - t * dy) ** 2 <= tolerance ** 2:
                return False
        if (ay > y) != (by > y):
            if x < ax + (y - ay) * dx / dy:
                inside = not inside
    return inside


def audit_modifier_positive_e(gcode, project, engine):
    """Require modifier coverage and safe negative-volume subtraction instead of model deposition inside each non-printing modifier's 3D bbox."""
    if not isinstance(gcode, bytes) or not 0 < len(gcode) <= 64 * 1024 * 1024:
        raise WorkerError("Invalid modifier G-code output.")
    boxes, kinds, meshes = modifier_bounds(project, engine, include_meshes=True)

    @lru_cache(maxsize=64)
    def section(index, layer_z):
        return _section_edges(meshes[index], layer_z)
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
                if kinds[i] == "negative_part":
                    # A generated perimeter exactly on the negative volume's
                    # boundary is not a filled cavity. Require strict interior
                    # deposition, with a small geometric tolerance, rather
                    # than rejecting legitimate surface contours.
                    inside = (all(low + 0.15 < value < high - 0.15
                                  for (low, high), value in zip(box, midpoint))
                              and _inside_section(midpoint[0], midpoint[1],
                                                  section(i, nz)))
                else:
                    inside = all(low - 0.05 <= value <= high + 0.05
                                 for (low, high), value in zip(box, midpoint))
                if inside:
                    hits[i] += 1
        x, y, z = nx, ny, nz
    if deposited < 10 or any(hits[i] == 0 for i,kind in enumerate(kinds)
                            if kind == "modifier_part"):
        raise WorkerError("Requested native modifier has no model deposition in the generated G-code.")
    # Successfully subtracting a negative region may remove ALL material there.
    # This requires zero positive-E paths, unlike a modifier. Comparative
    # pinned-binary fixture acceptance remains an independent prerequisite.
    if any(hits[i] > 0 for i,kind in enumerate(kinds)
           if kind == "negative_part"):
        raise WorkerError("Generated G-code deposits material inside a requested negative volume.")
    return {"modifier_count": len(boxes), "positive_e_paths": deposited,
            "modifier_region_paths": hits,
            "negative_volume_count": kinds.count("negative_part")}
