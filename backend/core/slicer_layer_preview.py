"""Full-resolution, read-only toolpaths for one requested G-code Z layer.

Unlike the global 80k-move overview sample, this parser retains consecutive
extrusion moves for one layer so bead geometry is not fragmented. The query
is bounded by G-code size and maximum layer moves; it never executes commands.
"""
import math
import re
from collections import Counter

from .slicer_preview import MOVE, TYPE, WIDTH

MAX_LAYER_SOURCE_BYTES = 32 * 1024 * 1024
MAX_LAYER_SEGMENTS = 75000


def exact_layer_toolpaths(text, target_z):
    """Return actual, ordered G0/G1 extrusion segments at target Z.

    Coordinates use [X1,Y1,X2,Y2,Z,feature,width] as the existing renderer
    expects. Never subsample a layer: if the bound is exceeded, return a
    clearly flagged incomplete layer instead of a visually misleading fill.
    """
    z_target = float(target_z)
    if not math.isfinite(z_target) or not 0 <= z_target <= 2000:
        raise ValueError("Invalid G-code layer Z.")
    absolute_xyz = True
    absolute_e = True
    x = y = z = e = 0.0
    role = "Other"
    width = None
    segments = []
    counts = Counter()
    total = 0

    for raw in text.splitlines():
        if len(raw) > 4096:
            continue
        line = raw.strip()
        if line.startswith(";"):
            matched = TYPE.match(line)
            if matched:
                role = matched.group(1).strip()[:48] or "Other"
            matched = WIDTH.match(line)
            if matched:
                value = float(matched.group(1))
                if math.isfinite(value) and 0.05 <= value <= 3:
                    width = round(value, 3)
            continue
        line = line.split(";", 1)[0].strip().upper()
        cmd = line.split(None, 1)[0] if line else ""
        if cmd == "G90":
            absolute_xyz = True
        elif cmd == "G91":
            absolute_xyz = False
        elif cmd == "M82":
            absolute_e = True
        elif cmd == "M83":
            absolute_e = False
        elif cmd == "G92":
            for key, raw_value in MOVE.findall(line[3:]):
                value = float(raw_value)
                if not math.isfinite(value):
                    continue
                if key == "E": e = value
                elif key == "X": x = value
                elif key == "Y": y = value
                elif key == "Z": z = value
        elif cmd in {"G0", "G00", "G1", "G01"}:
            nx, ny, nz, ne = x, y, z, e
            for key, raw_value in MOVE.findall(line[len(cmd):]):
                value = float(raw_value)
                if not math.isfinite(value) or abs(value) > 1000000:
                    continue
                if key == "X":
                    nx = value if absolute_xyz else x + value
                elif key == "Y":
                    ny = value if absolute_xyz else y + value
                elif key == "Z":
                    nz = value if absolute_xyz else z + value
                elif key == "E":
                    ne = value if absolute_e else e + value
            if (ne > e + 1e-6 and (nx != x or ny != y) and
                    math.isfinite(nz) and abs(nz - z_target) <= 0.0005):
                total += 1
                counts[role] += 1
                if len(segments) < MAX_LAYER_SEGMENTS:
                    segments.append([
                        round(x, 3), round(y, 3), round(nx, 3),
                        round(ny, 3), round(nz, 3), role, width,
                    ])
            x, y, z, e = nx, ny, nz, ne

    return {
        "z": round(z_target, 3),
        "segments": segments,
        "segment_count": total,
        "feature_counts": dict(counts),
        "complete": total <= MAX_LAYER_SEGMENTS,
        "sampled": False,
        "limited": total > MAX_LAYER_SEGMENTS,
    }
