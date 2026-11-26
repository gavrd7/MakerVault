"""Conservative, owner-scoped geometry guard for conflicting slicing drafts.

Only called during explicit slice scheduling. Checks three-dimensional AABB
of each transformed STL against the same centred-bed convention as preview.
Conservative AABBs guard 3D placement. For untilted meshes, a separating-axis
check of transformed XY bounding rectangles can prove disjoint placement even
when their world-axis boxes overlap. Uncertain pairs still fail closed.
"""
import itertools
import math

from .slicer_mesh import inspect_stl, MAX_INSPECTION_BYTES
from .slicer_plate_3mf import _transform


class PlateCollisionError(ValueError):
    pass


def _separated_planar_footprints(first, second):
    """Prove two rotated XY rectangles do not overlap.

    Their corners are conservative source-STL bounds, not triangle geometry.
    A separating axis can safely *permit* a pair; failure to find one
    conservatively leaves the existing overlap rejection in place.
    """
    for footprint in (first, second):
        for index in range(4):
            p = footprint[index]
            q = footprint[(index + 1) % 4]
            dx, dy = q[0] - p[0], q[1] - p[1]
            length = math.hypot(dx, dy)
            if not math.isfinite(length) or length < 1e-9:
                return False
            axis = (-dy / length, dx / length)
            a = [p[0] * axis[0] + p[1] * axis[1] for p in first]
            b = [p[0] * axis[0] + p[1] * axis[1] for p in second]
            if max(a) <= min(b) or max(b) <= min(a):
                return True
    return False


def validate_plate_collisions(objects_with_stl):
    bounds = []
    planar_footprints = []
    for item, raw in objects_with_stl:
        detail = inspect_stl(raw)
        size = detail["size_mm"]
        transform = [float(value) for value in _transform(item, 0, 0).split()]
        if len(transform) != 12 or any(not math.isfinite(v) for v in transform):
            raise PlateCollisionError("Invalid saved build plate model transform.")
        points = []
        for x, y, z in itertools.product(
            (-size[0] / 2, size[0] / 2),
            (-size[1] / 2, size[1] / 2),
            (0, size[2]),
        ):
            points.append((
                transform[0] * x + transform[3] * y + transform[6] * z + transform[9],
                transform[1] * x + transform[4] * y + transform[7] * z + transform[10],
                transform[2] * x + transform[5] * y + transform[8] * z,
            ))
        # When a model has no X/Y tilt, its transformed source bounding
        # rectangle is a conservative XY footprint. The rotated AABB can
        # overlap another rotated AABB even when these footprints are disjoint.
        # Tilted models retain the stricter 3D AABB check.
        if all(abs(transform[index]) < 1e-9 for index in (2, 5, 6, 7)):
            corners = (
                (-size[0] / 2, -size[1] / 2),
                (-size[0] / 2, size[1] / 2),
                (size[0] / 2, size[1] / 2),
                (size[0] / 2, -size[1] / 2),
            )
            planar_footprints.append([
                (transform[0] * x + transform[3] * y + transform[9],
                 transform[1] * x + transform[4] * y + transform[10])
                for x, y in corners
            ])
        else:
            planar_footprints.append(None)
        minz = min(p[2] for p in points)
        zbase = float(item.get("z_mm", 0))
        bounds.append((
            [min(p[i] for p in points) + (zbase - minz if i == 2 else 0) for i in range(3)],
            [max(p[i] for p in points) + (zbase - minz if i == 2 else 0) for i in range(3)],
        ))
    for i in range(len(bounds)):
        for j in range(i + 1, len(bounds)):
            first, second = bounds[i], bounds[j]
            if all(min(first[1][axis], second[1][axis]) -
                   max(first[0][axis], second[0][axis]) > 0.15
                   for axis in range(3)):
                if (planar_footprints[i] is not None and
                        planar_footprints[j] is not None and
                        _separated_planar_footprints(planar_footprints[i], planar_footprints[j])):
                    continue
                raise PlateCollisionError(
                    "Build plate contains intersecting model envelopes. "
                    "Separate the models before slicing; the draft remains available."
                )
    return True
