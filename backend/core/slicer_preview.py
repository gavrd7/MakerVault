"""Bounded, read-only preview of generated FDM G-code.

Never estimate print times by simply dividing travelled distance by speed:
acceleration, firmware motion planning and pauses make that misleading.
Only show explicit slicer-declared estimates. Geometry is sampled, not a
replacement for the slicer's native layer-by-layer simulation.
"""
import math
import re
from collections import Counter

MOVE = re.compile(r"([XYZEF])\s*([-+]?(?:\d+(?:\.\d*)?|\.\d+))", re.I)
DURATION = re.compile(r"^;\s*(?:estimated printing time(?: \(normal mode\))?|"
                      r"total estimated time|print time|printing time)\s*[:=]\s*(.+)$", re.I)
FILAMENT = re.compile(r"^;\s*filament used \[(mm|g|cm3)\]\s*[:=]\s*(.+)$", re.I)
TYPE = re.compile(r"^;\s*(?:TYPE|FEATURE)\s*:\s*([^;]+)", re.I)
MAX_SEGMENTS = 6000
MAX_LAYERS = 2000


def _duration_seconds(value):
    raw = value.strip().lower()
    try:
        if re.fullmatch(r"\d+(?:\.\d+)?", raw):
            seconds = float(raw)
        elif re.fullmatch(r"\d+(?::\d{1,2}){1,2}", raw):
            parts = [int(item) for item in raw.split(":")]
            seconds = sum(value * 60 ** index for index, value in enumerate(reversed(parts)))
        else:
            parts = re.findall(r"(\d+(?:\.\d+)?)\s*([dhms])", raw)
            if not parts or re.sub(r"(\d+(?:\.\d+)?)\s*[dhms]", "", raw).strip():
                return None
            seconds = sum(float(amount) * {"d": 86400, "h": 3600, "m": 60, "s": 1}[unit]
                          for amount, unit in parts)
        return round(seconds) if 0 < seconds < 60 * 60 * 24 * 365 else None
    except (ValueError, OverflowError):
        return None


def _filament_values(value):
    parts = re.split(r"[,;]", value.strip())
    if len(parts) > 16:
        return None
    try:
        numbers = [float(item.strip()) for item in parts]
    except ValueError:
        return None
    return round(sum(numbers), 2) if numbers and all(
        math.isfinite(n) and 0 <= n <= 100000000 for n in numbers) else None


def generated_preview(text, *, truncated=False):
    stats = {"estimated_time_seconds": None, "filament_mm": None,
             "filament_g": None, "filament_cm3": None,
             "layer_count": None, "layers": [], "segments": [],
             "segment_count": 0, "sampled": False, "complete": not truncated,
             "feature_counts": {}}
    absolute_xyz = True
    absolute_e = True
    x = y = z = e = 0.0
    feature = "Other"
    segments = []
    heights = set()
    counts = Counter()
    for raw in text.splitlines():
        if len(raw) > 4096:
            continue
        line = raw.strip()
        if line.startswith(";"):
            found = DURATION.match(line)
            if found and stats["estimated_time_seconds"] is None:
                stats["estimated_time_seconds"] = _duration_seconds(found.group(1))
            found = FILAMENT.match(line)
            if found:
                key = {"mm": "filament_mm", "g": "filament_g",
                       "cm3": "filament_cm3"}[found.group(1).lower()]
                if stats[key] is None:
                    stats[key] = _filament_values(found.group(2))
            found = TYPE.match(line)
            if found:
                feature = found.group(1).strip()[:48] or "Other"
            continue
        line = line.split(";", 1)[0].strip().upper()
        command = line.split(None, 1)[0] if line else ""
        if command in {"G90", "G91"}:
            absolute_xyz = command == "G90"
        elif command in {"M82", "M83"}:
            absolute_e = command == "M82"
        elif command == "G92":
            for key, raw_value in MOVE.findall(line[3:]):
                v = float(raw_value)
                if key == "E": e = v
                if key == "X": x = v
                if key == "Y": y = v
                if key == "Z": z = v
        elif command in {"G0", "G00", "G1", "G01"}:
            nx, ny, nz, ne = x, y, z, e
            supplied = set()
            for key, raw_value in MOVE.findall(line[len(command):]):
                supplied.add(key.upper())
                v = float(raw_value)
                if not math.isfinite(v) or abs(v) > 1000000:
                    continue
                if key.upper() == "X": nx = v if absolute_xyz else x + v
                if key.upper() == "Y": ny = v if absolute_xyz else y + v
                if key.upper() == "Z": nz = v if absolute_xyz else z + v
                if key.upper() == "E": ne = v if absolute_e else e + v
            delta = (ne - e if absolute_e else ne - e)
            if delta > 0.000001 and (nx != x or ny != y) and math.isfinite(nz):
                counts[feature] += 1
                if len(heights) < MAX_LAYERS:
                    heights.add(round(nz, 3))
                if len(segments) < MAX_SEGMENTS:
                    segments.append([round(x, 3), round(y, 3), round(nx, 3),
                                     round(ny, 3), round(nz, 3), feature])
                else:
                    stats["sampled"] = True
            x, y, z, e = nx, ny, nz, ne
    stats["segments"] = segments
    stats["segment_count"] = sum(counts.values())
    stats["feature_counts"] = dict(counts.most_common(12))
    if not stats["sampled"] and len(heights) < MAX_LAYERS and not truncated:
        stats["layers"] = sorted(heights)
        stats["layer_count"] = len(heights)
    else:
        stats["layers"] = sorted(heights)
        stats["sampled"] = True
    return stats
