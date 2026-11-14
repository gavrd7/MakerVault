"""Read exact rectangular XY plate bounds from a resolved native machine preset.

This deliberately rejects shifted, circular and exclusion-zone plates until
they have a verified mapping to MakerVault's centred visual coordinates.
"""
import json
import math
import re
from .slicer_profiles import SlicerProfileError
from .slicer_native_resolution import resolved_native_profile

CREALITY_POINT = re.compile(r"^([+-]?\d+(?:\.\d+)?)x([+-]?\d+(?:\.\d+)?)$")


def trusted_plate_dimensions(profile):
    if profile.kind != "printer":
        raise SlicerProfileError("A native machine profile is required.")
    raw = resolved_native_profile(profile)
    record = json.loads(raw)
    values = record.get("printable_area")
    if profile.engine == "crealityprint" and isinstance(values, str):
        points = []
        for raw_point in values.split(","):
            match = CREALITY_POINT.fullmatch(raw_point.strip())
            if not match:
                raise SlicerProfileError("Creality printable polygon is invalid.")
            points.append([float(match.group(1)), float(match.group(2))])
    elif profile.engine == "orcaslicer" and isinstance(values, list):
        points = []
        for raw_point in values:
            if not isinstance(raw_point, str):
                raise SlicerProfileError("Orca printable polygon is invalid.")
            match = CREALITY_POINT.fullmatch(raw_point.replace(",", "x").strip())
            if not match:
                raise SlicerProfileError("Orca printable polygon is invalid.")
            points.append([float(match.group(1)), float(match.group(2))])
    else:
        raise SlicerProfileError("Native printable geometry is not available.")
    if len(points) not in (4, 5) or any(not all(math.isfinite(v) for v in p) for p in points):
        raise SlicerProfileError("Rectangular native plate required for multi-object slicing.")
    if len(points) == 5 and points[-1] == points[0]:
        points.pop()
    xs, ys = [p[0] for p in points], [p[1] for p in points]
    xmin, xmax, ymin, ymax = min(xs), max(xs), min(ys), max(ys)
    expected = {(xmin, ymin), (xmin, ymax), (xmax, ymin), (xmax, ymax)}
    if (set(map(tuple, points)) != expected or len(set(map(tuple, points))) != 4
            or abs(xmin) > 0.01 or abs(ymin) > 0.01 or not 1 <= xmax <= 1000
            or not 1 <= ymax <= 1000):
        raise SlicerProfileError("Non-origin rectangular plates need a verified mapping.")
    # Bed cut-outs and excluded regions require their own checker.
    exclusion = record.get("bed_exclude_area") or record.get("printable_area_exclude")
    # Orca native parents commonly encode an empty exclusion as ["0x0"],
    # while printer children can encode the identical sentinel as "0x0".
    # Accept these exact empty sentinels, not arbitrary excluded areas.
    empty_exclusion = (
        exclusion is None or exclusion == "" or exclusion == "0" or
        exclusion == "0x0" or exclusion == [] or exclusion == ["0x0"] or
        exclusion == ["0"] or exclusion == ["0", "0"] or exclusion == "0x0,0x0"
    )
    if not empty_exclusion:
        raise SlicerProfileError(
            "Native printable-area exclusion is non-empty; mapped exclusion zones "
            "are not yet supported for multi-object slicing."
        )
    return float(xmax), float(ymax)
