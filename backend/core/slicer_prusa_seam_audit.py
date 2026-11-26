"""Prusa 2.9.7 painted seam spatial acceptance (one upright enforcer).

This proves actual first external-wall starts occur on the annotated face,
rather than merely trusting that a 3MF import or G-code process succeeded.
"""
import math
import re

WORD = re.compile(r"(?:^|\s)([XYZE])\s*([-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[Ee][-+]?\d+)?)", re.I)



def prusa_qualified_seam_direction(item):
    """Return (paint, face) for one fingerprinted upright Prusa seam patch.

    Native 2.9.7 independently measured all four vertical faces with
    seam_position=random; only the front face was qualified in the regular
    PrusaResearch process preset. Geometry signatures are rechecked by the
    3MF facet exporter; coordinates alone never authorise external paint.
    """
    from .slicer_semantic_painting import validate_semantic_paint
    if not isinstance(item, dict):
        raise ValueError("Prusa seam requires exactly one model.")
    try:
        selected = validate_semantic_paint(item.get("seam_paint"), "seam")
    except (ValueError, TypeError) as exc:
        raise ValueError("Prusa seam painting requires fingerprinted native regions.") from exc
    if selected["version"] != 2 or len(selected["regions"]) != 1:
        raise ValueError("Only one fingerprinted Prusa seam region is qualified.")
    region = selected["regions"][0]
    patches = region["patches"]
    if region["slot"] != 0 or not 1 <= len(patches) <= 2:
        raise ValueError("Only a single vertical seam enforcer is qualified.")
    if (item.get("colour_paint") or item.get("support_paint") or
            item.get("fuzzy_skin_paint") or item.get("modifier_volumes") or
            item.get("negative_volumes") or item.get("process_overrides") or
            (item.get("variable_layer_profile") or {}).get("bands")):
        raise ValueError("Prusa directional seam cannot combine unqualified edits.")
    try:
        if (abs(float(item.get("z_mm", 0))) > 1e-6 or
                abs(float(item.get("rotation_deg", 0))) > 1e-6 or
                any(abs(float(v)) > 1e-6
                    for v in item.get("rotation_xyz_deg", [0, 0])) or
                abs(float(item.get("scale_percent", 100))-100) > 1e-6 or
                any(abs(float(v)-100) > 1e-6
                    for v in item.get("scale_xyz_percent", [100, 100, 100]))):
            raise ValueError()
        points = [tuple(float(v) for v in pt)
                  for patch in patches for pt in patch["polygon"]]
        if (not points or any(len(pt) != 3 or any(
                not math.isfinite(value) or abs(value) > 1000
                for value in pt) for pt in points)):
            raise ValueError()
        xs = [pt[0] for pt in points]
        ys = [pt[1] for pt in points]
        zs = [pt[2] for pt in points]
        if max(zs)-min(zs) < 3:
            raise ValueError()
        if max(ys)-min(ys) <= .0001 and max(xs)-min(xs) >= 3:
            if abs(ys[0]) <= .001:
                raise ValueError()
            direction = "front" if ys[0] < 0 else "back"
        elif max(xs)-min(xs) <= .0001 and max(ys)-min(ys) >= 3:
            if abs(xs[0]) <= .001:
                raise ValueError()
            direction = "left" if xs[0] < 0 else "right"
        else:
            raise ValueError()
    except (KeyError, TypeError, ValueError, OverflowError):
        raise ValueError(
            "Only upright, unscaled Prusa vertical seam patches are qualified."
        ) from None
    return selected, direction


def validate_prusa_front_seam_candidate(item):
    """Retain strict front-only admission for legacy callers and presets."""
    selected, direction = prusa_qualified_seam_direction(item)
    if direction != "front":
        raise ValueError("Only Prusa front-face seams use the default native preset.")
    return selected


def audit_prusa_seam_enforcer_gcode(data, item, *, bed_width, bed_depth):
    paint = item.get("seam_paint") or {}
    regions = paint.get("regions") or []
    if len(regions) != 1 or regions[0].get("slot") != 0:
        raise ValueError("Prusa seam audit requires one enforcer region.")
    patches = regions[0].get("patches") or []
    if not 1 <= len(patches) <= 2:
        raise ValueError("Prusa seam audit requires one or two bounded patches.")
    polygons = [patch.get("polygon") for patch in patches if isinstance(patch, dict)]
    if len(polygons) != len(patches) or any(
            not isinstance(poly, list) or not 3 <= len(poly) <= 16
            for poly in polygons):
        raise ValueError("Prusa seam patch is invalid.")
    if (abs(float(item.get("z_mm", 0))) > 1e-6 or
            abs(float(item.get("rotation_deg", 0))) > 1e-6 or
            any(abs(float(v)) > 1e-6 for v in item.get("rotation_xyz_deg", [0, 0])) or
            any(abs(float(v)-100) > 1e-6 for v in
                item.get("scale_xyz_percent", [item.get("scale_percent", 100)]*3))):
        raise ValueError("Prusa painted seam requires an upright, unscaled model.")
    if not isinstance(data, bytes) or not 0 < len(data) <= 90*1024*1024:
        raise ValueError("Invalid Prusa native seam G-code.")
    try:
        points = [tuple(float(x) for x in p) for polygon in polygons for p in polygon]
        if any(len(p) != 3 or not all(math.isfinite(x) and abs(x) <= 1000 for x in p)
               for p in points):
            raise ValueError()
        ox = bed_width/2 + float(item.get("x_mm", 0))
        oy = bed_depth/2 + float(item.get("y_mm", 0))
        xmin = min(p[0] for p in points) + ox - .8
        xmax = max(p[0] for p in points) + ox + .8
        ymin = min(p[1] for p in points) + oy - .8
        ymax = max(p[1] for p in points) + oy + .8
        zmin, zmax = min(p[2] for p in points)+.5, max(p[2] for p in points)-.5
        if zmax-zmin < 3:
            raise ValueError()
        text = data.decode("utf-8")
    except (ValueError, TypeError, UnicodeDecodeError, OverflowError):
        raise ValueError("Prusa seam enforcer geometry or text is invalid.") from None
    pos = {"X": None, "Y": None, "Z": None}
    e, relative, relative_xy, role, captured = 0., False, False, "", False
    sampled = matching = 0
    for n, line in enumerate(text.splitlines()):
        if n > 2_000_000 or len(line) > 16384:
            raise ValueError("Prusa seam audit exceeds limits.")
        stripped = line.strip()
        if stripped == ";LAYER_CHANGE":
            captured = False
        elif stripped.startswith(";TYPE:"):
            role = stripped.partition(":")[2].lower()
        instruction = stripped.split(";", 1)[0].strip()
        if not instruction:
            continue
        op = instruction.split(None, 1)[0].upper()
        if op not in ("G0", "G00", "G1", "G01", "G90", "G91", "G92", "M82", "M83"):
            continue
        values = {k.upper():float(v) for k,v in WORD.findall(instruction)}
        if any(not math.isfinite(v) or abs(v) > 20000
               for k,v in values.items() if k != "E"):
            raise ValueError("Prusa seam G-code coordinates invalid.")
        if op == "M82":
            relative = False
        elif op == "M83":
            relative = True
        elif op == "G90":
            relative_xy = False
        elif op == "G91":
            relative_xy = True
        elif op == "G92":
            e = values.get("E", e)
            pos.update({k:v for k,v in values.items() if k in pos})
        else:
            old_xy = (pos["X"], pos["Y"])
            for axis in pos:
                if axis in values:
                    pos[axis] = (pos[axis] + values[axis]
                                 if relative_xy and pos[axis] is not None
                                 else None if relative_xy else values[axis])
            if "E" not in values:
                continue
            extruded = values["E"] if relative else values["E"]-e
            e = e+values["E"] if relative else values["E"]
            moved_xy = (old_xy[0] is not None and old_xy[1] is not None
                        and pos["X"] is not None and pos["Y"] is not None
                        and abs(pos["X"] - old_xy[0]) + abs(pos["Y"] - old_xy[1]) > 1e-7)
            if (not captured and op in ("G1", "G01") and moved_xy
                    and extruded > 1e-6 and role.strip() == "external perimeter"
                    and all(v is not None for v in pos.values())):
                captured = True
                if zmin <= pos["Z"] <= zmax:
                    sampled += 1
                    if xmin <= pos["X"] <= xmax and ymin <= pos["Y"] <= ymax:
                        matching += 1
    if sampled < 5 or matching < 5 or matching < math.ceil(.75*sampled):
        raise ValueError("Native Prusa seam did not follow the enforcer region.")
    return {"sampled_layers": sampled, "matching_layers": matching}
