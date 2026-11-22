"""Read-only Orca build-plate geometry from one unchanged native machine preset.

No implied printer compatibility: native inheritance, firmware offsets, bed
exclusions and object placement need independent validation by the engine.
"""
import math
import re

from .slicer_profile_lineage import _inspect_source
from .slicer_profiles import SlicerProfileError


POINT = re.compile(r"^\s*([+-]?\d+(?:\.\d+)?)\s*[xX,]\s*([+-]?\d+(?:\.\d+)?)\s*$")


def inspect_orca_plate(profile):
    if profile.engine != "orcaslicer" or profile.kind != "printer":
        raise SlicerProfileError("A native Orca machine profile is required.")
    data = _inspect_source(profile)
    parent = data.get("inherits")
    area = data.get("printable_area")
    height = data.get("printable_height")
    if height is None and parent:
        return {"status": "requires_parent", "parent": str(parent)[:200]}
    if not isinstance(area, list) or not (3 <= len(area) <= 24):
        if parent:
            return {"status": "requires_parent", "parent": str(parent)[:200]}
        return {"status": "unavailable", "reason": "Missing native printable-area polygon."}
    try:
        height = float(height)
        points = []
        for item in area:
            if not isinstance(item, str) or not (match := POINT.fullmatch(item)):
                raise ValueError("Invalid polygon")
            x, y = map(float, match.groups())
            if not all(math.isfinite(v) and abs(v) <= 10000 for v in (x, y)):
                raise ValueError("Invalid coordinate")
            points.append([x, y])
        if not math.isfinite(height) or not 0 < height <= 10000:
            raise ValueError("Invalid height")
        xmin, xmax = min(p[0] for p in points), max(p[0] for p in points)
        ymin, ymax = min(p[1] for p in points), max(p[1] for p in points)
        if xmax <= xmin or ymax <= ymin:
            raise ValueError("Degenerate polygon")
        signed_area = sum(
            points[i][0] * points[(i + 1) % len(points)][1] -
            points[(i + 1) % len(points)][0] * points[i][1]
            for i in range(len(points))
        )
        if abs(signed_area) < 0.01:
            raise ValueError("Zero polygon area")
    except (TypeError, ValueError, OverflowError):
        return {"status": "invalid", "reason": "Native printable geometry is malformed."}
    return {
        "status": "partial" if parent else "available",
        "parent": str(parent)[:200] if parent else None,
        "polygon_mm": points,
        "bounds_mm": {
            "min": [xmin, ymin, 0],
            "max": [xmax, ymax, height],
        },
        "size_mm": [round(xmax - xmin, 3), round(ymax - ymin, 3), round(height, 3)],
        "fit_check": "not_performed",
    }


def inspect_creality_plate(profile):
    """Display Creality's own declared K1/K2 bed without claiming slice safety."""
    if profile.engine != "crealityprint" or profile.kind != "printer":
        raise SlicerProfileError("A native Creality Print machine profile is required.")
    data = _inspect_source(profile)
    parent = data.get("inherits")
    area = data.get("printable_area")
    height = data.get("printable_height")
    if not isinstance(area, str) or height is None:
        return {"status": "requires_parent" if parent else "unavailable",
                "parent": str(parent)[:200] if parent else None}
    points = []
    try:
        for pair in area.split(","):
            match = POINT.fullmatch(pair)
            if not match:
                raise ValueError("Malformed native printable area")
            x, y = map(float, match.groups())
            if not all(math.isfinite(v) and abs(v) <= 10000 for v in (x, y)):
                raise ValueError("Invalid native coordinates")
            points.append([x, y])
        z = float(height)
        if len(points) not in (4, 5) or not math.isfinite(z) or not 0 < z <= 10000:
            raise ValueError("Unsupported native printable area")
        if len(points) == 5 and points[-1] == points[0]:
            points.pop()
        if len(points) != 4:
            raise ValueError("Unsupported polygon")
        xmin, xmax = min(p[0] for p in points), max(p[0] for p in points)
        ymin, ymax = min(p[1] for p in points), max(p[1] for p in points)
        if xmax <= xmin or ymax <= ymin or len(set(map(tuple, points))) != 4:
            raise ValueError("Invalid native bounds")
        if set(map(tuple, points)) != {
            (xmin, ymin), (xmin, ymax), (xmax, ymin), (xmax, ymax)
        }:
            raise ValueError("Non-rectangular native build plate")
    except (TypeError, ValueError, OverflowError):
        return {"status": "invalid", "reason": "Native Creality build area is malformed."}
    return {
        "status": "partial" if parent else "available",
        "parent": str(parent)[:200] if parent else None,
        "polygon_mm": points,
        "bounds_mm": {"min": [xmin, ymin, 0], "max": [xmax, ymax, z]},
        "size_mm": [round(xmax - xmin, 3), round(ymax - ymin, 3), round(z, 3)],
        "fit_check": "not_performed",
    }


def inspect_bambu_plate(profile):
    """UI-only geometry from a complete, owned, resolved native Bambu machine.

    This is not a slicer fit approval; the native machine may contain nonempty
    excluded regions that must be honored by the actual Bambu CLI.
    """
    import json
    from .slicer_native_resolution import resolved_native_profile
    if profile.engine != "bambustudio" or profile.kind != "printer":
        raise SlicerProfileError("A native Bambu machine profile is required.")
    data = json.loads(resolved_native_profile(profile))
    area, height = data.get("printable_area"), data.get("printable_height")
    if not isinstance(area, list) or not 3 <= len(area) <= 24:
        return {"status": "unavailable", "reason": "No resolved native printable-area polygon."}
    try:
        z = float(height[0] if isinstance(height, list) else height)
        points = []
        for vertex in area:
            match = POINT.fullmatch(vertex) if isinstance(vertex, str) else None
            if match is None:
                raise ValueError("Invalid native Bambu bed point")
            x, y = map(float, match.groups())
            if not all(math.isfinite(v) and 0 <= v <= 10000 for v in (x, y)):
                raise ValueError("Invalid native Bambu bed coordinate")
            points.append([x, y])
        if not math.isfinite(z) or not 0 < z <= 10000:
            raise ValueError("Invalid native Bambu build height")
        xmin, xmax = min(x for x, _ in points), max(x for x, _ in points)
        ymin, ymax = min(y for _, y in points), max(y for _, y in points)
        if xmax <= xmin or ymax <= ymin or abs(xmin) > .01 or abs(ymin) > .01:
            raise ValueError("Invalid native Bambu bed extents")
    except (ValueError, TypeError, OverflowError):
        return {"status": "invalid", "reason": "Native Bambu printable geometry is malformed."}
    return {
        "status": "available", "polygon_mm": points,
        "bounds_mm": {"min": [xmin, ymin, 0], "max": [xmax, ymax, z]},
        "size_mm": [round(xmax - xmin, 3), round(ymax - ymin, 3), round(z, 3)],
        "fit_check": "not_performed",
        "has_exclusion_zone": bool(data.get("bed_exclude_area")
                                   and data["bed_exclude_area"] not in (["0x0"], [])),
    }
