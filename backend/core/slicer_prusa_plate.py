"""Prusa-only, single-material native STL plate with exact preview transforms.

This does not create a Prusa 3MF project, smuggle object settings into
profiles, or modify the established Orca/Creality/Bambu plate exporters.
All source STLs must already have passed owner and integrity checks.
"""
import math
import re
import struct

from .slicer_plate_3mf import _triangles, _transform
from .slicer_mesh import inspect_stl, MeshInspectionError
from .slicer_profiles import SlicerProfileError

_BED_POINT = re.compile(r"^([+-]?\d+(?:\.\d+)?)x([+-]?\d+(?:\.\d+)?)$")


def prusa_native_bed_dimensions(native_ini):
    """Fail closed for shifted, nonrectangular or excluded Prusa native beds."""
    if not isinstance(native_ini, bytes) or len(native_ini) > 2 * 1024 * 1024:
        raise SlicerProfileError("Invalid native Prusa bed profile.")
    try:
        lines = native_ini.decode("utf-8").splitlines()
    except UnicodeDecodeError as exc:
        raise SlicerProfileError("Invalid native Prusa profile encoding.") from exc
    settings = {}
    for line in lines:
        if "=" in line and not line.lstrip().startswith((";", "#")):
            k, v = line.split("=", 1)
            key = k.strip()
            if key in settings:
                raise SlicerProfileError("Ambiguous native Prusa bed profile.")
            settings[key] = v.strip()
    if settings.get("printer_technology", "FFF") != "FFF":
        raise SlicerProfileError("Prusa bed requires an FFF printer.")
    if settings.get("bed_exclude_area", "") not in ("", "0x0"):
        raise SlicerProfileError("Prusa excluded bed regions are not yet verified.")
    raw = settings.get("bed_shape", "")
    points = []
    for part in raw.split(","):
        match = _BED_POINT.fullmatch(part.strip())
        if not match:
            raise SlicerProfileError("Prusa native bed polygon is invalid.")
        points.append((float(match.group(1)), float(match.group(2))))
    if len(points) == 5 and points[-1] == points[0]:
        points.pop()
    if len(points) != 4 or not all(math.isfinite(v) for p in points for v in p):
        raise SlicerProfileError("Prusa native rectangular bed is required.")
    xs, ys = [p[0] for p in points], [p[1] for p in points]
    xmin, xmax, ymin, ymax = min(xs), max(xs), min(ys), max(ys)
    corners = {(xmin, ymin), (xmin, ymax), (xmax, ymin), (xmax, ymax)}
    if (len(set(points)) != 4 or set(points) != corners or
            abs(xmin) > 0.01 or abs(ymin) > 0.01 or
            not 1 <= xmax <= 1000 or not 1 <= ymax <= 1000):
        raise SlicerProfileError("Only origin-rectangular Prusa beds are verified.")
    return float(xmax), float(ymax)


# Legacy native profile capacity constants are retained for explicit callers,
# but no longer imposed as arbitrary defaults on ordinary Prusa plates.
MAX_FACES = 500_000
MAX_STL_BYTES = 32 * 1024 * 1024


def build_prusa_placed_stl(objects_with_stl, *, bed_width, bed_depth,
                           max_faces=None, max_stl_bytes=None):
    """Use the released engine-independent, resource-aware placed-STL path.

    Preserve source ownership, per-object transforms, native rectangular-bed
    checks and strict object-setting admission. Native Prusa-specific *optional*
    capacity constraints remain enforceable by callers that need them. The
    shared executor preserves exact STL facets and can prepare independent
    sources in bounded parallel subprocesses.
    """
    if max_faces is not None and (
            type(max_faces) is not int or not 1 <= max_faces <= 1_500_000):
        raise SlicerProfileError("Invalid bounded native STL triangle budget.")
    if max_stl_bytes is not None and (
            type(max_stl_bytes) is not int or max_stl_bytes <= 84
            or max_stl_bytes > 80 * 1024 * 1024):
        raise SlicerProfileError("Invalid bounded native STL byte budget.")

    from .slicer_placed_stl import build_placed_stl
    result = build_placed_stl(
        objects_with_stl, bed_width=bed_width, bed_depth=bed_depth)
    count = struct.unpack_from("<I", result, 80)[0]
    if ((max_faces is not None and count > max_faces)
            or (max_stl_bytes is not None and len(result) > max_stl_bytes)):
        raise SlicerProfileError("Prusa plate exceeds the explicitly requested native STL budget.")
    return result
