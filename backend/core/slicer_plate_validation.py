"""Conservative, owner-scoped geometry guard for conflicting slicing drafts.

Only called during explicit slice scheduling. Checks three-dimensional AABB
of each transformed STL against the same centred-bed convention as preview.
Bounding boxes can report false positives for curved/diagonal objects: reject
uncertain collisions rather than silently merging overlapping solids.
"""
import itertools
import math

from .slicer_mesh import inspect_stl, MAX_INSPECTION_BYTES
from .slicer_plate_3mf import _transform


class PlateCollisionError(ValueError):
    pass


def validate_plate_collisions(objects_with_stl):
    bounds = []
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
                raise PlateCollisionError(
                    "Build plate contains intersecting model envelopes. "
                    "Separate the models before slicing; the draft remains available."
                )
    return True
