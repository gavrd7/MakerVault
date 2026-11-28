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


def _inside_triangle(point, triangle, *, margin=0.02):
    """Strict projected containment; ignore nozzle transitions at paint edges."""
    (ax, ay), (bx, by), (cx, cy) = triangle
    denominator = (by - cy) * (ax - cx) + (cx - bx) * (ay - cy)
    if abs(denominator) <= 1e-10:
        return False
    u = ((by - cy) * (point[0] - cx) +
         (cx - bx) * (point[1] - cy)) / denominator
    v = ((cy - ay) * (point[0] - cx) +
         (ax - cx) * (point[1] - cy)) / denominator
    w = 1 - u - v
    return min(u, v, w) > margin


def audit_prusa_partial_wall_gcode(data, project, *, tool, tower=None):
    """Research-only spatial deposition audit for a split vertical colour mask.

    Use verified native 3MF facet polygons and actual positive-E external
    perimeter moves at their Z heights. Both endpoints must be on the source
    wall. Counts exclude stationary priming, travel, boundary uncertainty,
    wrong extrusion roles and other model regions. Passing this independent
    audit is not permission to enable the production slice/print route.
    """
    import re

    source = inspect_prusa_partial_wall(project, tool)
    if not isinstance(data, bytes) or not 0 < len(data) <= 90 * 1024 * 1024:
        raise WorkerError("Invalid Prusa partial-mask G-code.")
    if tower is not None:
        if (not isinstance(tower, (tuple, list)) or len(tower) != 5 or
                any(type(v) not in (int, float) or not math.isfinite(v)
                    for v in tower)):
            raise WorkerError("Invalid Prusa partial colour tower geometry.")
        tx, ty = tower[:2]
        tower_box = (tx - 6, tx + 65, ty - 12, ty + 45)
    else:
        tower_box = None
    axis = source["axis"]
    tangent = 1 - axis
    plane = source["plane"]
    selected = {0, tool}
    counts = {t: {"painted": 0, "unpainted": 0} for t in selected}
    layers = {t: {"painted": set(), "unpainted": set()} for t in selected}
    purge = {t: 0 for t in selected}
    role = ""
    active = None
    position = [None, None, None]
    extruder = 0.0
    relative_e = relative_xyz = False
    number = re.compile(r"(?:^|\s)([XYZE])\s*([-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[Ee][-+]?\d+)?)", re.I)
    for index, raw in enumerate(io.BytesIO(data)):
        if index >= 2_000_000 or len(raw) > 16384:
            raise WorkerError("Prusa partial-mask G-code exceeds audit limits.")
        try:
            line = raw.decode("utf-8").strip()
        except UnicodeDecodeError:
            raise WorkerError("Prusa partial-mask G-code must be UTF-8.") from None
        if line.startswith(";TYPE:"):
            role = line.partition(":")[2].strip().lower()
        cmd = line.split(";", 1)[0].strip()
        if not cmd:
            continue
        op = cmd.split(None, 1)[0].upper()
        if op.startswith("T") and op[1:].isdigit():
            active = int(op[1:])
            if active not in selected:
                raise WorkerError("Unexpected Prusa partial-mask tool.")
            continue
        if op not in ("G90", "G91", "G92", "M82", "M83",
                      "G0", "G00", "G1", "G01"):
            continue
        words = {key.upper(): float(value) for key, value in number.findall(cmd)}
        if any(not math.isfinite(value) or abs(value) > 1e9
               for value in words.values()):
            raise WorkerError("Nonfinite Prusa partial-mask motion.")
        if op == "G90":
            relative_xyz = False
        elif op == "G91":
            relative_xyz = True
        elif op == "M82":
            relative_e = False
        elif op == "M83":
            relative_e = True
        elif op == "G92":
            extruder = words.get("E", extruder)
            for i, key in enumerate(("X", "Y", "Z")):
                if key in words:
                    position[i] = words[key]
        else:
            previous = tuple(position)
            for i, key in enumerate(("X", "Y", "Z")):
                if key in words:
                    position[i] = (
                        (position[i] + words[key])
                        if relative_xyz and position[i] is not None
                        else None if relative_xyz else words[key])
            if "E" not in words:
                continue
            delta = words["E"] if relative_e else words["E"] - extruder
            extruder = extruder + words["E"] if relative_e else words["E"]
            if (delta > 1e-6 and active in selected and
                    op in ("G1", "G01") and tower_box is not None and
                    previous[0] is not None and previous[1] is not None and
                    position[0] is not None and position[1] is not None and
                    tower_box[0] <= previous[0] <= tower_box[1] and
                    tower_box[2] <= previous[1] <= tower_box[3] and
                    tower_box[0] <= position[0] <= tower_box[1] and
                    tower_box[2] <= position[1] <= tower_box[3]):
                purge[active] += 1
            if (op not in ("G1", "G01") or delta <= 1e-6 or
                    active not in selected or role != "external perimeter" or
                    any(v is None for v in previous + tuple(position))):
                continue
            if (abs(previous[axis] - plane) > 1.5 or
                    abs(position[axis] - plane) > 1.5 or
                    abs(previous[tangent] - position[tangent]) < 1e-5 or
                    abs(previous[2] - position[2]) > 0.001):
                continue
            midpoint = ((previous[tangent] + position[tangent]) / 2,
                        position[2])
            hits = [kind for kind in ("painted", "unpainted") if any(
                _inside_triangle(midpoint, tri)
                for tri in source[kind])]
            if len(hits) != 1:
                continue
            kind = hits[0]
            counts[active][kind] += 1
            layers[active][kind].add(round(position[2], 3))
    if (counts[tool]["painted"] < 8 or
            counts[0]["unpainted"] < 8 or
            len(layers[tool]["painted"]) < 3 or
            len(layers[0]["unpainted"]) < 3 or
            # Genuine Prusa 2.9.7 can lay a small amount of T0 base
            # foundation on a T1-painted corner (observed 7 vs 64 T1
            # selected movements). Do not equate this with T1 leakage into
            # the unpainted mask. Require T0 in the painted region to stay
            # below 12.5% of selected T1 deposition, with a two-move
            # edge/junction allowance for small fixtures.
            counts[0]["painted"] > max(2, counts[tool]["painted"] // 8) or
            counts[tool]["unpainted"] > 2):
        raise WorkerError(
            "Prusa partial-surface colour deposition did not match signed masks "
            "(selected painted=%d, base unpainted=%d, selected other=%d, "
            "base painted=%d, painted layers=%d, unpainted layers=%d)." % (
                counts[tool]["painted"], counts[0]["unpainted"],
                counts[tool]["unpainted"], counts[0]["painted"],
                len(layers[tool]["painted"]), len(layers[0]["unpainted"])))
    if tower_box is not None and any(value < 10 for value in purge.values()):
        raise WorkerError(
            "Prusa partial-mask G-code lacks native tool-specific wipe tower purging "
            "(base=%d, painted=%d)." % (purge[0], purge[tool]))
    return {
        "tower_extrusion_moves": purge if tower_box is not None else None,
        "tool": tool,
        "deposition_moves": counts,
        "painted_layers": len(layers[tool]["painted"]),
        "unpainted_layers": len(layers[0]["unpainted"]),
        "offline_only": True,
    }


def qualified_prusa_single_colour_mode(project, tool):
    """Classify a signed source mask, never a browser-supplied feature flag.

    Native worker admission separately limits material topologies: MMU may
    use complete/split vertical walls; genuine XL5 additionally supports a
    partially painted horizontal top. Angled, curved and other masks fail.
    """
    from .prusa_colour_gcode_audit import _wall_regions

    try:
        _wall_regions(project, tool)
        return "complete_wall"
    except WorkerError:
        pass
    try:
        inspect_prusa_partial_wall(project, tool)
        return "split_wall"
    except WorkerError:
        pass
    from .prusa_top_surface import inspect_prusa_partial_top
    try:
        inspect_prusa_partial_top(project, tool)
        return "split_top"
    except WorkerError:
        pass
    from .prusa_slanted_surface import inspect_prusa_slanted_surface
    inspect_prusa_slanted_surface(project, tool)
    return "split_slanted"
