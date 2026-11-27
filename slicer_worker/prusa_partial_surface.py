"""Worker-side geometry contract for partial Prusa TriangleSelector colour masks.

This module inspects the *signed native 3MF*, never browser-provided paint
coordinates. It is deliberately separate from the proven complete-wall G-code
auditor: a geometrically valid split mask is not proof of correct deposition.
"""
import io
import math
import zipfile

from defusedxml import ElementTree as SafeET

from .prusa_material_validation import MODEL, PAINT
from .prusa_colour_gcode_audit import NS, PAINTED_STATES
from .runner import WorkerError


def inspect_prusa_partial_wall(project, tool):
    """Describe a truly partial vertical painted wall for a future G-code audit.

    Return the source-plane triangles for selected-tool and unpainted cells.
    A full painted wall, a nonvertical patch, a foreign tool, a missing
    ModelPart, or malformed coordinates fails closed. This function does NOT
    authorise the worker to slice or submit the file.
    """
    if type(tool) is not int or tool not in PAINTED_STATES.values():
        raise WorkerError("Invalid Prusa partial-mask tool.")
    if not isinstance(project, bytes) or not 0 < len(project) <= 32 * 1024 * 1024:
        raise WorkerError("Invalid Prusa partial-mask project.")
    try:
        with zipfile.ZipFile(io.BytesIO(project)) as archive:
            root = SafeET.fromstring(archive.read(MODEL))
            config = SafeET.fromstring(archive.read("Metadata/Slic3r_PE_model.config"))
        objects = root.findall("./" + NS + "resources/" + NS + "object")
        configs = config.findall("./object")
        if len(objects) != 1 or len(configs) != 1:
            raise ValueError("Expected one native object")
        vertices = objects[0].findall("./" + NS + "mesh/" + NS + "vertices/" + NS + "vertex")
        faces = objects[0].findall("./" + NS + "mesh/" + NS + "triangles/" + NS + "triangle")
        volumes = configs[0].findall("./volume")
        if (not 3 <= len(vertices) <= 1_500_000 or
                not 4 <= len(faces) <= 500_000 or not volumes or
                volumes[0].get("firstid") != "0" or
                not any(meta.get("key") == "volume_type" and
                        meta.get("value") == "ModelPart"
                        for meta in volumes[0].findall("./metadata"))):
            raise ValueError("Invalid ModelPart")
        end = int(volumes[0].get("lastid", "-1"))
        if not 3 <= end < len(faces):
            raise ValueError("Invalid printable mesh range")
        if any(face.get(PAINT) is not None for face in faces[end + 1:]):
            raise ValueError("Painting on nonprinting geometry")
        points = [tuple(float(v.get(key)) for key in ("x", "y", "z"))
                  for v in vertices]
        if any(not all(math.isfinite(n) and abs(n) < 2000 for n in p)
               for p in points):
            raise ValueError("Invalid coordinates")
        regions = []
        state = next(name for name, selected in PAINTED_STATES.items()
                     if selected == tool)
        for face in faces[:end + 1]:
            polygon = tuple(points[int(face.get(key))]
                            for key in ("v1", "v2", "v3"))
            if len(set(polygon)) != 3:
                raise ValueError("Degenerate face")
            regions.append((polygon, face.get(PAINT)))
        painted = [poly for poly, attr in regions if attr == state]
        if not painted:
            raise ValueError("No selected colour facets")
        # Choose one actual exterior X or Y plane from the selected polygons.
        # Vertical slice qualification is deliberately narrower than arbitrary
        # angled/curved paint and cannot be mistaken for complete feature parity.
        qualified = []
        for axis in (0, 1):
            positions = [p[axis] for poly, _ in regions for p in poly]
            for plane in (min(positions), max(positions)):
                if not all(abs(p[axis] - plane) < 0.0001
                           for poly in painted for p in poly):
                    continue
                wall = [(poly, attr) for poly, attr in regions
                        if all(abs(p[axis] - plane) < 0.0001 for p in poly)]
                if any(attr == state and pair not in wall for pair in regions
                       for poly, attr in [pair]):
                    continue
                plain = [poly for poly, attr in wall if attr is None]
                if not plain:
                    continue
                tangent = 1 - axis
                def projected(poly):
                    return tuple((p[tangent], p[2]) for p in poly)
                def area(poly):
                    a, b, c = projected(poly)
                    return abs((b[0] - a[0]) * (c[1] - a[1]) -
                               (b[1] - a[1]) * (c[0] - a[0])) * .5
                painted_area = sum(area(p) for p in painted)
                plain_area = sum(area(p) for p in plain)
                if painted_area <= .01 or plain_area <= .01:
                    continue
                qualified.append({
                    "axis": axis, "plane": plane, "tool": tool,
                    "painted": tuple(projected(p) for p in painted),
                    "unpainted": tuple(projected(p) for p in plain),
                    "painted_area_mm2": round(painted_area, 5),
                    "unpainted_area_mm2": round(plain_area, 5),
                })
        if len(qualified) != 1:
            raise ValueError("Partial mask has no unambiguous vertical wall")
        return qualified[0]
    except (OSError, ValueError, TypeError, IndexError, KeyError, StopIteration,
            OverflowError, AttributeError, zipfile.BadZipFile):
        raise WorkerError("Prusa native partial paint is not a qualified vertical surface.") from None
