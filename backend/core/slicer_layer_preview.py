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
from .slicer_preview_features import overview_priority, is_prime_tower_feature, is_support_feature

MAX_LAYER_SOURCE_BYTES = 32 * 1024 * 1024
MAX_LAYER_SEGMENTS = 75000
MAX_BATCH_SEGMENTS = 180000
MAX_BATCH_LAYERS = 64
MAX_OVERVIEW_SEGMENTS_PER_LAYER = 450


def _overview_segments(segments, per_layer_limit=MAX_OVERVIEW_SEGMENTS_PER_LAYER):
    """Bound a prepared overview, reserving surface paths for towers/supports.

    Never infer or fabricate geometry: all retained segments originate in
    the native G-code. This also drives the lighter mobile cache variant.
    """
    if len(segments) <= per_layer_limit:
        return segments
    tower = []
    supports = []
    model = []
    for index, segment in enumerate(segments):
        if is_prime_tower_feature(segment[5]):
            tower.append(index)
        elif is_support_feature(segment[5]):
            supports.append(index)
        else:
            model.append(index)

    def spaced(indices, count):
        if count <= 0:
            return []
        if len(indices) <= count:
            return indices
        return [indices[min(len(indices)-1, (i*len(indices))//count)]
                for i in range(count)]

    tower_selected=spaced(tower, min(len(tower), max(24, per_layer_limit//3)))
    support_selected=spaced(supports, min(len(supports), max(16, per_layer_limit//5)))
    capacity=per_layer_limit-len(tower_selected)-len(support_selected)
    by_priority={}
    for index in model:
        by_priority.setdefault(overview_priority(segments[index][5]), []).append(index)
    selected=tower_selected+support_selected
    for priority in sorted(by_priority):
        if capacity <= 0:
            break
        chosen=spaced(by_priority[priority], capacity)
        selected.extend(chosen)
        capacity-=len(chosen)
    # Return unused model capacity to support and tower paths if necessary.
    if capacity:
        seen=set(selected)
        remaining=[i for i in supports+tower if i not in seen]
        selected.extend(spaced(remaining, capacity))
    return [segments[index] for index in sorted(selected)]


def layer_batch_toolpaths(text, target_zs, *, overview=False, overview_limit=350, max_requested_layers=MAX_BATCH_LAYERS):
    """Return actual, ordered G0/G1 extrusion segments at target Z.

    Coordinates use [X1,Y1,X2,Y2,Z,feature,width,logical_tool] as the existing renderer
    expects. Never subsample a layer: if the bound is exceeded, return a
    clearly flagged incomplete layer instead of a visually misleading fill.
    """
    if not isinstance(target_zs, (list, tuple)) or not 1 <= len(target_zs) <= max_requested_layers:
        raise ValueError("Choose between 1 and 64 layers.")
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
                         **({"overview_heap": [], "tower_heap": [], "support_heap": []} if overview else {})}
                 for height in targets}
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
                        if overview:
                            # Keep a small, distributed set of visible surfaces
                            # as we scan. Never accumulate the full 3D print in
                            # Python merely to throw most of it away afterwards.
                            sequence = layer["segment_count"]
                            tower_move = is_prime_tower_feature(role)
                            support_move = is_support_feature(role)
                            priority = overview_priority(role)
                            spread = ((sequence * 2654435761) & 0xffffffff)
                            rank = (-priority, spread, sequence)
                            # Retain geometry for distinct physical structures
                            # even on layers dominated by outer-wall moves.
                            heap = (layer["tower_heap"] if tower_move
                                    else layer["support_heap"] if support_move
                                    else layer["overview_heap"])
                            quota = (max(24, overview_limit // 3) if tower_move
                                     else max(16, overview_limit // 5) if support_move
                                     else overview_limit)
                            if len(heap) < quota or rank > heap[0][:3]:
                                segment = [round(px,3), round(py,3),
                                           round(ax,3), round(ay,3),
                                           key,role,width,tool]
                                entry = (*rank, segment)
                                if len(heap) < overview_limit:
                                    heapq.heappush(heap, entry)
                                else:
                                    heapq.heapreplace(heap, entry)
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
        if overview:
            general=layer.pop("overview_heap")
            tower=layer.pop("tower_heap")
            supports=layer.pop("support_heap")
            keep_general=max(0, overview_limit-len(tower)-len(supports))
            best_general=heapq.nlargest(keep_general, general) if keep_general else []
            selected=best_general+tower+supports
            layer["segments"] = [entry[3] for entry in sorted(selected, key=lambda row: row[2])]
            layer["overview_reduced"] = len(layer["segments"]) < original
        layer["feature_counts"] = dict(layer["feature_counts"])
        layer["complete"] = True if overview else original_captured == original
        layer["sampled"] = bool(overview and layer.get("overview_reduced"))
        layer["limited"] = not layer["complete"]
    return {"layers": [by_height[height] for height in targets],
            "complete": all(layer["complete"] for layer in by_height.values()),
            "sampled": overview,
            "overview": overview}


def exact_layer_toolpaths(text, target_z):
    """Maintain the original single-layer API for precise movement inspection."""
    return layer_batch_toolpaths(text, [target_z])["layers"][0]
