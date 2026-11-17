"""Full-resolution, read-only toolpaths for one requested G-code Z layer.

Unlike the global 80k-move overview sample, this parser retains consecutive
extrusion moves for one layer so bead geometry is not fragmented. The query
is bounded by G-code size and maximum layer moves; it never executes commands.
"""
import math
import re
from collections import Counter

from .slicer_preview import MOVE, TYPE, WIDTH, ARC_PARAM
from .slicer_preview_arcs import arc_points

MAX_LAYER_SOURCE_BYTES = 32 * 1024 * 1024
MAX_LAYER_SEGMENTS = 75000
MAX_BATCH_SEGMENTS = 180000
MAX_BATCH_LAYERS = 64
MAX_OVERVIEW_SEGMENTS_PER_LAYER = 450


def _overview_segments(segments, per_layer_limit=MAX_OVERVIEW_SEGMENTS_PER_LAYER):
    """Bound the 3D overview by feature while preserving original move geometry.

    Prioritise visible shells, interfaces and supports. Never claim the
    reduced overview is an exact toolpath; exact-layer inspection is separate.
    """
    from .slicer_preview_features import overview_priority
    if len(segments) <= per_layer_limit:
        return segments
    groups = {}
    for index, segment in enumerate(segments):
        priority = overview_priority(segment[5])
        groups.setdefault(priority, []).append(index)
    kept = []
    for priority in sorted(groups):
        indices = groups[priority]
        space = per_layer_limit - len(kept)
        if space <= 0:
            break
        if len(indices) <= space:
            kept.extend(indices)
        else:
            # Uniformly distributed endpoints avoid retaining only the first
            # portion of a shell when it exceeds the per-layer budget.
            count = max(1, space)
            kept.extend(indices[min(len(indices)-1, (i * len(indices)) // count)]
                        for i in range(count))
            break
    return [segments[index] for index in sorted(kept)]


def layer_batch_toolpaths(text, target_zs, *, overview=False):
    """Return actual, ordered G0/G1 extrusion segments at target Z.

    Coordinates use [X1,Y1,X2,Y2,Z,feature,width,logical_tool] as the existing renderer
    expects. Never subsample a layer: if the bound is exceeded, return a
    clearly flagged incomplete layer instead of a visually misleading fill.
    """
    if not isinstance(target_zs, (list, tuple)) or not 1 <= len(target_zs) <= MAX_BATCH_LAYERS:
        raise ValueError("Choose between 1 and 64 layers.")
    targets = []
    for value in target_zs:
        height = float(value)
        if not math.isfinite(height) or not 0 <= height <= 2000:
            raise ValueError("Invalid G-code layer Z.")
        height = round(height, 3)
        if height in targets:
            raise ValueError("Duplicate G-code layer Z.")
        targets.append(height)
    selected = set(targets)
    by_height = {height: {"z": height, "segments": [], "segment_count": 0,
                         "feature_counts": Counter()} for height in targets}
    absolute_xyz = True
    absolute_e = True
    absolute_centres = False
    x = y = z = e = 0.0
    role = "Other"
    width = None
    stored_count = 0
    tool = None

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
        if len(cmd) in (2, 3) and cmd.startswith("T") and cmd[1:].isdigit():
            candidate = int(cmd[1:])
            if cmd == "T" + str(candidate) and candidate < 16 and line == cmd:
                tool = candidate
                continue
        if cmd == "G90":
            absolute_xyz = True
        elif cmd == "G91":
            absolute_xyz = False
        elif cmd == "M82":
            absolute_e = True
        elif cmd == "M83":
            absolute_e = False
        elif cmd in {"G90.1","G91.1"}:
            absolute_centres = cmd == "G90.1"
        elif cmd == "G92":
            for key, raw_value in MOVE.findall(line[3:]):
                value = float(raw_value)
                if not math.isfinite(value):
                    continue
                if key == "E": e = value
                elif key == "X": x = value
                elif key == "Y": y = value
                elif key == "Z": z = value
        elif cmd in {"G0","G00","G1","G01","G2","G02","G3","G03"}:
            nx,ny,nz,ne=x,y,z,e
            for key,raw_value in MOVE.findall(line[len(cmd):]):
                value=float(raw_value)
                if not math.isfinite(value) or abs(value)>1000000:
                    continue
                if key=="X": nx=value if absolute_xyz else x+value
                elif key=="Y": ny=value if absolute_xyz else y+value
                elif key=="Z": nz=value if absolute_xyz else z+value
                elif key=="E": ne=value if absolute_e else e+value
            is_arc=cmd in {"G2","G02","G3","G03"}
            if is_arc:
                args={key.upper():float(v) for key,v in ARC_PARAM.findall(line[len(cmd):])}
                moves=arc_points(x,y,z,nx,ny,nz,cmd in {"G2","G02"},args,
                                 absolute_centres=absolute_centres)
            else:
                moves=[(nx,ny,nz,1.0)] if nx!=x or ny!=y else None
            if ne>e+1e-6 and moves:
                px,py,pz=x,y,z
                for ax,ay,az,_ in moves:
                    key = round(az, 3)
                    if math.hypot(ax-px,ay-py)>1e-6 and key in selected:
                        layer = by_height[key]
                        layer["segment_count"] += 1
                        layer["feature_counts"][role] += 1
                        if (len(layer["segments"]) < MAX_LAYER_SEGMENTS and
                                stored_count < MAX_BATCH_SEGMENTS):
                            layer["segments"].append([round(px,3),round(py,3),
                                                       round(ax,3),round(ay,3),
                                                       key,role,width,tool])
                            stored_count += 1
                    px,py,pz=ax,ay,az
            x,y,z,e=nx,ny,nz,ne

    for layer in by_height.values():
        original = layer["segment_count"]
        if overview:
            layer["segments"] = _overview_segments(layer["segments"])
            layer["overview_reduced"] = len(layer["segments"]) < original
        layer["feature_counts"] = dict(layer["feature_counts"])
        layer["complete"] = (len(layer["segments"]) == layer["segment_count"]) if not overview else (
            original <= MAX_LAYER_SEGMENTS and not (
                stored_count >= MAX_BATCH_SEGMENTS and
                len(layer["segments"]) == 0 and original > 0))
        layer["sampled"] = bool(overview and layer.get("overview_reduced"))
        layer["limited"] = not layer["complete"]
    return {"layers": [by_height[height] for height in targets],
            "complete": all(layer["complete"] for layer in by_height.values()),
            "sampled": overview,
            "overview": overview}


def exact_layer_toolpaths(text, target_z):
    """Maintain the original single-layer API for precise movement inspection."""
    return layer_batch_toolpaths(text, [target_z])["layers"][0]
