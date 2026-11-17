"""Translate precise MakerVault support paint patches into native Orca facets.

No face-wide approximation: intersect clipped model-local convex paint patches
with their source STL triangles and re-triangulate ONLY affected source faces.
The geometry is unchanged to sub-micron tolerance; each resulting native
3MF triangle gets paint_supports=4 (enforcer) or 8 (blocker), matching
OrcaSlicer 2.5.0 TriangleSelector's unsplit-leaf state nibble.
This is OFFLINE TEST input, never a printer authorisation.
"""
import math

from .slicer_support_painting import validate_support_paint
from .slicer_semantic_painting import validate_semantic_paint

MAX_NATIVE_PAINT_TRIANGLES = 500_000
EPS = 1e-8


def _minus(a, b):
    return tuple(x - y for x, y in zip(a, b))


def _cross(a, b):
    return (a[1]*b[2]-a[2]*b[1], a[2]*b[0]-a[0]*b[2],
            a[0]*b[1]-a[1]*b[0])


def _dot(a, b):
    return sum(x*y for x, y in zip(a, b))


def _normal(tri):
    return _cross(_minus(tri[1], tri[0]), _minus(tri[2], tri[0]))


def _area(poly, unit):
    return abs(sum(_dot(_cross(_minus(poly[i], poly[0]),
                                _minus(poly[i+1], poly[0])), unit)
                   for i in range(1, len(poly)-1))) * .5


def _clip(poly, a, edge, normal, inside):
    """Convex polygon clipped against a cutter edge; preserves source winding."""
    def dist(point):
        value = _dot(_cross(edge, _minus(point, a)), normal)
        return value if inside else -value
    if not poly:
        return []
    result = []
    previous = poly[-1]
    pd = dist(previous)
    for point in poly:
        current = dist(point)
        previous_in = pd >= -EPS
        current_in = current >= -EPS
        if previous_in != current_in and abs(pd-current) > EPS:
            t = pd / (pd-current)
            result.append(tuple(previous[i]+t*(point[i]-previous[i]) for i in range(3)))
        if current_in:
            result.append(point)
        previous, pd = point, current
    cleaned = []
    for p in result:
        if not cleaned or math.dist(p, cleaned[-1]) > 1e-7:
            cleaned.append(p)
    if len(cleaned)>1 and math.dist(cleaned[0],cleaned[-1]) < 1e-7:
        cleaned.pop()
    return cleaned


def _pieces(source, cutter, normal):
    """Convex subtraction returns outside cells and the painted intersection."""
    remaining = source
    outside = []
    for i, a in enumerate(cutter):
        edge = _minus(cutter[(i+1)%len(cutter)], a)
        cutout = _clip(remaining, a, edge, normal, False)
        if len(cutout)>=3 and _area(cutout, normal)>1e-8:
            outside.append(cutout)
        remaining = _clip(remaining, a, edge, normal, True)
        if len(remaining)<3 or _area(remaining, normal)<=1e-8:
            return [source], []
    return outside, remaining


def _triangulate(poly, unit):
    for i in range(1, len(poly)-1):
        tri = (poly[0], poly[i], poly[i+1])
        if _area(tri, unit)>1e-8:
            yield tri


def _fingerprint(triangles):
    """Exactly match slicerColourPainting.js createPaintMesh's face signature."""
    h = 2166136261
    for tri in triangles:
        for point in tri:
            for coordinate in point:
                value = math.floor(coordinate * 10000 + .5)
                h = ((h ^ (value & 0xffffffff)) * 16777619) & 0xffffffff
    return str(len(triangles)) + ":" + format(h, "x")


def native_support_triangles(triangles, paint, *, kind="support"):
    """Yield (STL-order triangle, native annotation or None).

    Fail closed if the mesh changed, a patch lies off-face, paints overlap,
    the clipped area is unaccounted for, or re-meshing exceeds the limit.
    """
    if not paint or not paint.get("regions"):
        return [(tri, None) for tri in triangles]
    if kind not in ("support", "seam", "fuzzy"):
        raise ValueError("Unsupported native painted facet type.")
    data = (validate_support_paint(paint) if kind == "support"
            else validate_semantic_paint(paint, kind))
    # STLLoader's preview geometry is centred in X/Y and grounded at min Z
    # BEFORE MakerVault computes the paint signature and local brush patches.
    minimum = [min(p[axis] for face in triangles for p in face) for axis in range(3)]
    maximum = [max(p[axis] for face in triangles for p in face) for axis in range(3)]
    origin = ((minimum[0]+maximum[0]) / 2, (minimum[1]+maximum[1]) / 2, minimum[2])
    local_triangles = [
        [tuple(float(p[axis])-origin[axis] for axis in range(3)) for p in face]
        for face in triangles
    ]
    if data["signature"] != _fingerprint(local_triangles):
        raise ValueError("Support painting mesh fingerprint no longer matches the source STL.")
    by_face = {}
    for region in data["regions"]:
        for patch in region["patches"]:
            by_face.setdefault(patch["face"], []).append((region["slot"],patch["polygon"]))
    output = []
    for index, source in enumerate(local_triangles):
        patches = by_face.get(index)
        if not patches:
            output.append((source, None))
            continue
        normal = _normal(source)
        length = math.sqrt(_dot(normal, normal))
        if length <= 1e-10:
            raise ValueError("Painted source triangle is degenerate.")
        unit = tuple(n/length for n in normal)
        free = [source]
        painted = []
        for slot, polygon in patches:
            if kind == "fuzzy" and slot != 0:
                raise ValueError("Native fuzzy skin painting supports only the painted state.")
            cutter = [tuple(float(v) for v in point) for point in polygon]
            if _dot(_normal(cutter[:3]), unit) < 0:
                cutter.reverse()
            # Region vertices must lie within the source face, in its plane.
            for pt in cutter:
                if abs(_dot(_minus(pt,source[0]),unit)) > .0001:
                    raise ValueError("Support patch is not coplanar with its source triangle.")
                if not all(_dot(_cross(_minus(source[(i+1)%3], source[i]),
                                           _minus(pt, source[i])),unit) >= -0.0001
                           for i in range(3)):
                    raise ValueError("Support patch lies outside its source triangle.")
            for existing, previous_slot in painted:
                _, duplicate = _pieces(existing, cutter, unit)
                if duplicate and _area(duplicate, unit) > 1e-6:
                    raise ValueError(
                        "Overlapping support paint patches must be resolved in the editor.")
            next_free = []
            for cell in free:
                outside, overlap = _pieces(cell,cutter,unit)
                next_free.extend(outside)
                if overlap:
                    painted.append((overlap,slot))
            free = next_free
        total_area = sum(_area(poly,unit) for poly in free) + sum(
            _area(poly,unit) for poly,_ in painted)
        if abs(total_area-_area(source,unit)) > max(1e-6,_area(source,unit)*1e-4):
            raise ValueError("Support painting changed source mesh coverage.")
        for poly in free:
            output.extend((tri,None) for tri in _triangulate(poly,unit))
        for poly, slot in painted:
            output.extend((tri,"4" if slot==0 else "8")
                          for tri in _triangulate(poly,unit))
        if len(output)>MAX_NATIVE_PAINT_TRIANGLES:
            raise ValueError("Native support painting exceeds the safe mesh triangle limit.")
    if not any(attr for _, attr in output):
        raise ValueError("Native "+kind+" painting did not produce any annotated facets.")
    # Restore original STL-local coordinates. _render_mesh owns the one and
    # only placement-centering pass used for native 3MF model geometry.
    return [
        (tuple(tuple(p[axis]+origin[axis] for axis in range(3)) for p in tri), state)
        for tri, state in output
    ]


PAINT_CHANNELS = (
    ("support", "support_paint", "paint_supports"),
    ("seam", "seam_paint", "paint_seam"),
    ("fuzzy", "fuzzy_skin_paint", "paint_fuzzy_skin"),
)


def native_combined_paint_triangles(triangles, support=None, seam=None, fuzzy=None):
    """Split each *original* STL facet once into disjoint cells carrying all
    native paint attributes. Overlap between different painting modes is legal;
    overlap within one mode is rejected. No channel may silently disappear.
    This path is intended only for offline Orca 2.5 testing.
    """
    paints = (support, seam, fuzzy)
    active = [(kind, attribute, paint) for (kind, _field, attribute), paint
              in zip(PAINT_CHANNELS, paints)
              if isinstance(paint, dict) and paint.get("regions")]
    if len(active) < 2:
        raise ValueError("Combined painting requires at least two active channels.")
    if not triangles:
        raise ValueError("Painted mesh is empty.")
    minimum = [min(p[axis] for face in triangles for p in face) for axis in range(3)]
    maximum = [max(p[axis] for face in triangles for p in face) for axis in range(3)]
    origin = ((minimum[0]+maximum[0])/2, (minimum[1]+maximum[1])/2, minimum[2])
    local = [
        [tuple(float(p[axis])-origin[axis] for axis in range(3)) for p in face]
        for face in triangles
    ]
    signature = _fingerprint(local)
    channel_faces = {}
    for kind, attribute, paint in active:
        validated = (validate_support_paint(paint) if kind == "support"
                     else validate_semantic_paint(paint, kind))
        if validated["signature"] != signature:
            raise ValueError(kind + " painting mesh fingerprint no longer matches the source STL.")
        indexed = {}
        for region in validated["regions"]:
            slot = region["slot"]
            if kind == "fuzzy" and slot != 0:
                raise ValueError("Native fuzzy skin only accepts painted facets.")
            for patch in region["patches"]:
                face = patch["face"]
                if not 0 <= face < len(local):
                    raise ValueError(kind + " patch references a missing source face.")
                indexed.setdefault(face, []).append((slot, patch["polygon"]))
        channel_faces[attribute] = indexed

    output = []
    painted_counts = {attribute: 0 for _kind, attribute, _paint in active}
    for index, source in enumerate(local):
        normal = _normal(source)
        length = math.sqrt(_dot(normal, normal))
        if length <= 1e-10:
            if any(index in channel_faces[attr] for attr in channel_faces):
                raise ValueError("Painted source triangle is degenerate.")
            output.append((source, {}))
            continue
        unit = tuple(value/length for value in normal)
        # Each disjoint cell retains every previously assigned channel.
        cells = [(source, {})]
        for kind, attribute, _paint in active:
            patches = channel_faces[attribute].get(index, ())
            # Paints within the same channel must not overlap, even though
            # overlap across *different* channels is intentionally supported.
            previous_patches = []
            for slot, polygon in patches:
                cutter = [tuple(float(v) for v in point) for point in polygon]
                if _dot(_normal(cutter[:3]), unit) < 0:
                    cutter.reverse()
                for pt in cutter:
                    if abs(_dot(_minus(pt, source[0]), unit)) > .0001:
                        raise ValueError(kind + " patch is not coplanar with its source face.")
                    if not all(_dot(_cross(
                            _minus(source[(i+1)%3], source[i]),
                            _minus(pt, source[i])), unit) >= -0.0001
                            for i in range(3)):
                        raise ValueError(kind + " patch lies outside its source face.")
                for prev in previous_patches:
                    _outside, intersection = _pieces(prev, cutter, unit)
                    if intersection and _area(intersection, unit) > 1e-6:
                        raise ValueError("Overlapping " + kind + " patches must be resolved in the editor.")
                previous_patches.append(cutter)
                next_cells = []
                for cell, attributes in cells:
                    outside, inside = _pieces(cell, cutter, unit)
                    next_cells.extend((part, attributes) for part in outside)
                    if inside:
                        if attribute in attributes:
                            raise ValueError("Overlapping " + kind + " patches must be resolved in the editor.")
                        next_cells.append((inside, {**attributes, attribute: "4" if slot == 0 else "8"}))
                cells = next_cells
                if len(cells) + len(output) > MAX_NATIVE_PAINT_TRIANGLES:
                    raise ValueError("Combined native painting exceeds the safe mesh limit.")
        total = sum(_area(cell, unit) for cell, _attributes in cells)
        if abs(total - _area(source, unit)) > max(1e-6, _area(source, unit)*1e-4):
            raise ValueError("Combined painting changed source mesh coverage.")
        for cell, attributes in cells:
            for tri in _triangulate(cell, unit):
                output.append((tuple(tuple(p[axis]+origin[axis] for axis in range(3))
                                     for p in tri), attributes))
                for attribute in attributes:
                    painted_counts[attribute] += 1
                if len(output) > MAX_NATIVE_PAINT_TRIANGLES:
                    raise ValueError("Combined native painting exceeds the safe triangle limit.")
    if any(count == 0 for count in painted_counts.values()):
        raise ValueError("One or more native painted channels yielded no annotated facets.")
    return output
