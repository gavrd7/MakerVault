"""Full-resolution, read-only toolpaths for one requested G-code Z layer.

Unlike the global 80k-move overview sample, this parser retains consecutive
extrusion moves for one layer so bead geometry is not fragmented. The query
is bounded by G-code size and maximum layer moves; it never executes commands.
"""
import heapq
import math
import re
from collections import Counter

from .slicer_preview import MOVE, TYPE, WIDTH, ARC_PARAM
from .slicer_preview_arcs import arc_points
from .slicer_preview_features import overview_family, balanced_overview_indices

MAX_LAYER_SOURCE_BYTES = 32 * 1024 * 1024
MAX_LAYER_SEGMENTS = 75000
MAX_BATCH_SEGMENTS = 180000
MAX_BATCH_LAYERS = 64
MAX_FULL_PREVIEW_SEGMENTS = 1500000
MAX_OVERVIEW_SEGMENTS_PER_LAYER = 450
OVERVIEW_WEIGHTS = {
    "tower": .18, "support": .20, "shell": .26,
    "skin": .16, "inner": .12, "body": .08,
}


def _overview_segments(segments, per_layer_limit=MAX_OVERVIEW_SEGMENTS_PER_LAYER):
    """Reduce a cached desktop overview for mobile without losing features.

    Groups are based only on the native G-code's role markers. The output is
    always a chronological subset of original extrusion moves.
    """
    if len(segments) <= per_layer_limit:
        return segments
    groups = {}
    for index, segment in enumerate(segments):
        groups.setdefault(overview_family(segment[5]), []).append(index)
    return [segments[i] for i in balanced_overview_indices(groups, per_layer_limit)]


def _append_continuous_bead(layer, move, max_records, budget, motion_token):
    """Keep every path; collapse only exactly aligned adjacent straight moves.

    No path subsampling. A join is permitted solely for adjacent extrusions
    from the same material/feature/width whose centreline is collinear within
    0.015 mm and whose direction does not reverse. Travel breaks continuity.
    """
    segments = layer["segments"]
    previous = segments[-1] if segments else None
    if (previous and layer.get("last_token") == motion_token and
            previous[4:] == move[4:] and
            abs(previous[2] - move[0]) <= 0.0005 and
            abs(previous[3] - move[1]) <= 0.0005):
        ax, ay = previous[0], previous[1]
        bx, by = previous[2], previous[3]
        cx, cy = move[2], move[3]
        abx, aby = bx-ax, by-ay
        acx, acy = cx-ax, cy-ay
        length = math.hypot(acx, acy)
        if (length > 1e-6 and abx*(cx-bx)+aby*(cy-by) >= 0 and
                abs(abx*acy-aby*acx)/length < 0.015):
            previous[2], previous[3] = move[2], move[3]
            layer["last_token"] = motion_token
            return True
    if len(segments) >= max_records or budget[0] >= budget[1]:
        layer["last_token"] = None
        return False
    segments.append(move)
    budget[0] += 1
    layer["last_token"] = motion_token
    return True


def layer_batch_toolpaths(text, target_zs, *, overview=False, overview_limit=350,
                          high_fidelity=False, max_requested_layers=MAX_BATCH_LAYERS,
                          max_total_segments=MAX_BATCH_SEGMENTS):
    """Return actual, ordered G0/G1 extrusion segments at target Z.

    Coordinates use [X1,Y1,X2,Y2,Z,feature,width,logical_tool] as the existing renderer
    expects. Never subsample a layer: if the bound is exceeded, return a
    clearly flagged incomplete layer instead of a visually misleading fill.
    """
    if not isinstance(target_zs, (list, tuple)) or not 1 <= len(target_zs) <= max_requested_layers:
        raise ValueError("Choose between 1 and 64 layers.")
    if overview and high_fidelity:
        raise ValueError("Choose one preview geometry mode.")
    if high_fidelity and not 1 <= max_total_segments <= MAX_FULL_PREVIEW_SEGMENTS:
        raise ValueError("Invalid full preview geometry budget.")
    if (overview and (isinstance(overview_limit, bool) or not isinstance(overview_limit, int)
                     or not 80 <= overview_limit <= MAX_OVERVIEW_SEGMENTS_PER_LAYER)):
        raise ValueError("Invalid preview detail level.")
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
                         "feature_counts": Counter(), "captured_count": 0,
                         **({"last_token": None} if high_fidelity else {}),
                         **({"overview_heap": [], "feature_heaps": {}} if overview else {})}
                 for height in targets}
    absolute_xyz = True
    absolute_e = True
    absolute_centres = False
    x = y = z = e = 0.0
    role = "Other"
    family = overview_family(role)
    width = None
    stored_count = 0
    budget = [0, max_total_segments]
    motion_token = 0
    tool = None

    for raw in text.splitlines():
        if len(raw) > 4096:
            continue
        line = raw.strip()
        if line.startswith(";"):
            matched = TYPE.match(line)
            if matched:
                role = matched.group(1).strip()[:48] or "Other"
                family = overview_family(role)
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
            if high_fidelity and (ne <= e+1e-6 or not moves):
                # Constant-time travel barrier: unlike resetting every layer
                # this costs O(1) even on 700-layer prints with many moves.
                motion_token += 1
            if ne>e+1e-6 and moves:
                px,py,pz=x,y,z
                for ax,ay,az,_ in moves:
                    key = round(az, 3)
                    if math.hypot(ax-px,ay-py)>1e-6 and key in selected:
                        layer = by_height[key]
                        layer["segment_count"] += 1
                        layer["feature_counts"][role] += 1
                        if high_fidelity:
                            bead=[round(px,3), round(py,3),
                                  round(ax,3), round(ay,3),
                                  key,role,width,tool]
                            if _append_continuous_bead(
                                    layer, bead, MAX_LAYER_SEGMENTS, budget, motion_token):
                                layer["captured_count"] += 1
                        elif overview:
                            # Keep a small, distributed set of visible surfaces
                            # as we scan. Never accumulate the full 3D print in
                            # Python merely to throw most of it away afterwards.
                            sequence = layer["segment_count"]
                            spread = (sequence * 2654435761) & 0xffffffff
                            rank = (spread, sequence)
                            global_heap = layer["overview_heap"]
                            family_heap = layer["feature_heaps"].setdefault(family, [])
                            minimum = 24 if family == "tower" else 16 if family == "support" else 8
                            quota = max(minimum, int(overview_limit * OVERVIEW_WEIGHTS[family]))
                            global_needed = (len(global_heap) < overview_limit or
                                             rank > global_heap[0][:2])
                            family_needed = (len(family_heap) < quota or
                                             rank > family_heap[0][:2])
                            # Avoid allocating and rounding an 8-field record
                            # for every discarded move on low-spec servers.
                            if global_needed or family_needed:
                                record = [round(px,3), round(py,3),
                                          round(ax,3), round(ay,3),
                                          key,role,width,tool]
                                entry = (*rank, record)
                                if global_needed:
                                    if len(global_heap) < overview_limit:
                                        heapq.heappush(global_heap, entry)
                                    else:
                                        heapq.heapreplace(global_heap, entry)
                                if family_needed:
                                    if len(family_heap) < quota:
                                        heapq.heappush(family_heap, entry)
                                    else:
                                        heapq.heapreplace(family_heap, entry)
                        elif (len(layer["segments"]) < MAX_LAYER_SEGMENTS and
                              stored_count < MAX_BATCH_SEGMENTS):
                            layer["segments"].append([round(px,3),round(py,3),
                                                       round(ax,3),round(ay,3),
                                                       key,role,width,tool])
                            stored_count += 1
                            layer["captured_count"] += 1
                    px,py,pz=ax,ay,az
            x,y,z,e=nx,ny,nz,ne

    for layer in by_height.values():
        original = layer["segment_count"]
        original_captured=layer.pop("captured_count")
        layer.pop("last_token", None)
        if overview:
            candidates = {
                entry[1]: entry[2]
                for entry in layer.pop("overview_heap")
            }
            for heap in layer.pop("feature_heaps").values():
                for entry in heap:
                    candidates[entry[1]] = entry[2]
            ordered = sorted(candidates.items())
            groups = {}
            for index, (sequence, segment) in enumerate(ordered):
                groups.setdefault(overview_family(segment[5]), []).append(index)
            selected_indices = balanced_overview_indices(groups, overview_limit)
            layer["segments"] = [ordered[index][1] for index in selected_indices]
            layer["overview_reduced"] = len(layer["segments"]) < original
        layer["feature_counts"] = dict(layer["feature_counts"])
        layer["complete"] = True if overview else original_captured == original
        layer["sampled"] = bool(overview and layer.get("overview_reduced"))
        layer["limited"] = not layer["complete"]
    return {"layers": [by_height[height] for height in targets],
            "complete": all(layer["complete"] for layer in by_height.values()),
            "sampled": overview,
            "overview": overview,
            "high_fidelity": high_fidelity}


def exact_layer_toolpaths(text, target_z):
    """Maintain the original single-layer API for precise movement inspection."""
    return layer_batch_toolpaths(text, [target_z])["layers"][0]
