"""Prusa 2.9.7 painted seam spatial acceptance (one upright enforcer).

This proves actual first external-wall starts occur on the annotated face,
rather than merely trusting that a 3MF import or G-code process succeeded.
"""
import math
import re

WORD = re.compile(r"(?:^|\s)([XYZE])\s*([-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[Ee][-+]?\d+)?)", re.I)



def validate_prusa_front_seam_candidate(item):
    """Admit the one proven Prusa 2.9.7 seam orientation, not all paint faces.

    The native front-direction acceptance proved first perimeter extrusion
    starts follow an enforcer region on a Y-negative upright face. Reject
    back, right, left, tilted and mixed painting until individually qualified.
    """
    from .slicer_semantic_painting import validate_semantic_paint
    if not isinstance(item, dict):
        raise ValueError("Prusa front seam requires one model.")
    paint=item.get("seam_paint")
    selected=validate_semantic_paint(paint,"seam")
    if selected["version"]!=2 or len(selected["regions"])!=1:
        raise ValueError("Only one fingerprinted Prusa front seam region is qualified.")
    region=selected["regions"][0]
    patches=region["patches"]
    if region["slot"]!=0 or not 1<=len(patches)<=2:
        raise ValueError("Only a front-face seam enforcer is qualified.")
    if (item.get("colour_paint") or item.get("support_paint") or
            item.get("fuzzy_skin_paint") or item.get("modifier_volumes") or
            item.get("negative_volumes") or item.get("process_overrides") or
            (item.get("variable_layer_profile") or {}).get("bands")):
        raise ValueError("Prusa front seam cannot combine unqualified edits.")
    try:
        if (abs(float(item.get("z_mm",0)))>1e-6 or
                abs(float(item.get("rotation_deg",0)))>1e-6 or
                any(abs(float(v))>1e-6 for v in item.get("rotation_xyz_deg",[0,0])) or
                any(abs(float(v)-100)>1e-6 for v in item.get(
                    "scale_xyz_percent",[item.get("scale_percent",100)]*3))):
            raise ValueError()
        points=[tuple(float(v) for v in pt)
                for patch in patches for pt in patch["polygon"]]
        if (not points or any(len(pt)!=3 or any(
                not math.isfinite(value) or abs(value)>1000 for value in pt)
                for pt in points)):
            raise ValueError()
        # The known successful direction is the model-local front plane
        # (negative Y) with a meaningful X/Z span. A tiny mark on a side,
        # top, bottom or unpainted neighbour has no native evidence.
        y=points[0][1]
        if (y>=-.001 or any(abs(pt[1]-y)>.0001 for pt in points)
                or max(pt[0] for pt in points)-min(pt[0] for pt in points)<3
                or max(pt[2] for pt in points)-min(pt[2] for pt in points)<3):
            raise ValueError()
    except (KeyError,TypeError,ValueError,OverflowError):
        raise ValueError("Only upright, unscaled Prusa front-face seam patches are qualified.") from None
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
    e, relative, role, captured = 0., False, "", False
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
        if op not in ("G0", "G00", "G1", "G01", "G92", "M82", "M83"):
            continue
        values = {k.upper():float(v) for k,v in WORD.findall(instruction)}
        if any(not math.isfinite(v) or abs(v) > 20000
               for k,v in values.items() if k != "E"):
            raise ValueError("Prusa seam G-code coordinates invalid.")
        if op == "M82":
            relative = False
        elif op == "M83":
            relative = True
        elif op == "G92":
            e = values.get("E", e)
        else:
            pos.update({k:v for k,v in values.items() if k in pos})
            if "E" not in values:
                continue
            extruded = values["E"] if relative else values["E"]-e
            e = e+values["E"] if relative else values["E"]
            if (not captured and extruded > 1e-6 and "external perimeter" in role
                    and all(v is not None for v in pos.values())):
                captured = True
                if zmin <= pos["Z"] <= zmax:
                    sampled += 1
                    if xmin <= pos["X"] <= xmax and ymin <= pos["Y"] <= ymax:
                        matching += 1
    if sampled < 5 or matching < 5 or matching < math.ceil(.75*sampled):
        raise ValueError("Native Prusa seam did not follow the enforcer region.")
    return {"sampled_layers": sampled, "matching_layers": matching}
