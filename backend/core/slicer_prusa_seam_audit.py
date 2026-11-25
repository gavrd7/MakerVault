"""Prusa 2.9.7 painted seam spatial acceptance (one upright enforcer).

This proves actual first external-wall starts occur on the annotated face,
rather than merely trusting that a 3MF import or G-code process succeeded.
"""
import math
import re

WORD = re.compile(r"(?:^|\s)([XYZE])\s*([-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[Ee][-+]?\d+)?)", re.I)


def audit_prusa_seam_enforcer_gcode(data, item, *, bed_width, bed_depth):
    paint = item.get("seam_paint") or {}
    regions = paint.get("regions") or []
    if len(regions) != 1 or regions[0].get("slot") != 0:
        raise ValueError("Prusa seam audit requires one enforcer region.")
    patches = regions[0].get("patches") or []
    if len(patches) != 1:
        raise ValueError("Prusa seam audit requires one bounded patch.")
    polygon = patches[0].get("polygon")
    if not isinstance(polygon, list) or not 3 <= len(polygon) <= 16:
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
        points = [tuple(float(x) for x in p) for p in polygon]
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
