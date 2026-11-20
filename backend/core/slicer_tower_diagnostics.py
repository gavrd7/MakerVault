"""Bounded offline G-code prime/wipe tower geometry measurements.

This is deliberately conservative: only explicit native feature markers
identify tower deposition. Unlabelled extrusion is NOT classified as a tower.
No G-code, printer macros or private coordinates are returned to callers.
"""
import math
import re

_FEATURE = re.compile(r"^;\s*(?:TYPE|FEATURE)\s*:\s*(.*)$", re.I)
_TOWER = re.compile(r"\b(?:prime|purge|wipe)[ _-]*tower\b", re.I)
_AXIS = re.compile(r"(?<![A-Za-z])([XYZE])([-+]?(?:\d+(?:\.\d*)?|\.\d+))", re.I)
_MOVE = re.compile(r"^G0?[01](?:\s|$)", re.I)
_LIMIT = 64 * 1024 * 1024


def tower_deposition_metrics(gcode):
    """Measure positively extruded X/Y moves explicitly tagged as tower.

    Coordinates and E may be absolute or relative; G92 E resets are honoured.
    Reports raw filament mm, NOT volume or physical purge (diameter and
    firmware-owned extrusion are intentionally outside this parser).
    """
    if not isinstance(gcode, bytes) or len(gcode) > _LIMIT:
        raise ValueError("Invalid bounded tower G-code input.")
    text = gcode.decode("utf-8", errors="replace")
    x = y = e = 0.0
    xyz_absolute = True
    e_absolute = True
    tower = False
    count = 0
    distance = extrusion = 0.0
    xmin = ymin = math.inf
    xmax = ymax = -math.inf
    feature_markers = 0
    for line in text.splitlines():
        raw = line.strip()
        match = _FEATURE.match(raw)
        if match:
            tower = bool(_TOWER.search(match.group(1)))
            if tower:
                feature_markers += 1
            continue
        command = raw.partition(";")[0].strip().upper()
        if not command:
            continue
        op = command.split(None, 1)[0]
        if op == "G90":
            xyz_absolute = True
            continue
        if op == "G91":
            xyz_absolute = False
            continue
        if op == "M82":
            e_absolute = True
            continue
        if op == "M83":
            e_absolute = False
            continue
        if op == "G92":
            axes = {key.upper(): float(value) for key, value in _AXIS.findall(command)}
            if "X" in axes: x = axes["X"]
            if "Y" in axes: y = axes["Y"]
            if "E" in axes: e = axes["E"]
            continue
        if not _MOVE.match(command):
            continue
        axes = {key.upper(): float(value) for key, value in _AXIS.findall(command)}
        if any(not math.isfinite(v) or abs(v) > 100000 for v in axes.values()):
            raise ValueError("Invalid motion number in native tower diagnostic.")
        next_x = (axes["X"] if xyz_absolute else x + axes["X"]) if "X" in axes else x
        next_y = (axes["Y"] if xyz_absolute else y + axes["Y"]) if "Y" in axes else y
        next_e = (axes["E"] if e_absolute else e + axes["E"]) if "E" in axes else e
        delta_e = next_e - e if "E" in axes else 0
        planar = math.hypot(next_x - x, next_y - y)
        if tower and delta_e > 0 and planar > 0:
            count += 1
            distance += planar
            extrusion += delta_e
            xmin, xmax = min(xmin, x, next_x), max(xmax, x, next_x)
            ymin, ymax = min(ymin, y, next_y), max(ymax, y, next_y)
        x, y, e = next_x, next_y, next_e
    measured = count > 0
    return {
        "classification": "native_feature_marker" if measured else "unavailable_no_verified_tower_moves",
        "tower_feature_markers": feature_markers,
        "deposition_moves": count,
        "xy_width_mm": round(xmax - xmin, 3) if measured else None,
        "xy_depth_mm": round(ymax - ymin, 3) if measured else None,
        "xy_path_length_mm": round(distance, 3) if measured else None,
        "positive_e_length_mm": round(extrusion, 3) if measured else None,
        "note": "Tower-only measurements require native TYPE/FEATURE tower markers; unclassified moves are not attributed to the tower.",
    }
