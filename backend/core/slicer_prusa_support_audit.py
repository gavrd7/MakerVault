"""Spatial G-code acceptance for two separate Prusa support-painted objects.

Native Prusa 2.9.7 research proved that apparent support leakage was
stationary E recovery, not support deposition. Never infer isolation from
positive E alone: each counted path must actually move within one model's
trusted independently baked XY footprint.
"""
import io
import math
import re

from .slicer_prusa_spatial_layers import _bounds

WORD = re.compile(r"(?:^|\s)([XYZE])\s*([-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[Ee][-+]?\d+)?)", re.I)
ROLES = frozenset(("support material", "support material interface"))


def validate_prusa_two_support_plate(plate):
    """Restrict the new acceptance route to exactly one painted and one plain object."""
    if not isinstance(plate, list) or len(plate) != 2 or any(
            not isinstance(row, dict) for row in plate):
        raise ValueError("Prusa independent support painting requires two objects.")
    painted = [
        i for i, row in enumerate(plate)
        if (row.get("support_paint") or {}).get("regions")
    ]
    if len(painted) != 1:
        raise ValueError("Prusa independent support painting requires exactly one enforcer.")
    for row in plate:
        support = row.get("support_paint") or {}
        if (support.get("faces") or row.get("process_overrides")
                or row.get("modifier_volumes") or row.get("negative_volumes")
                or (row.get("variable_layer_profile") or {}).get("bands")
                or (row.get("seam_paint") or {}).get("regions")
                or (row.get("seam_paint") or {}).get("faces")
                or (row.get("fuzzy_skin_paint") or {}).get("regions")
                or (row.get("fuzzy_skin_paint") or {}).get("faces")
                or (row.get("colour_paint") or {}).get("regions")
                or (row.get("colour_paint") or {}).get("faces")):
            raise ValueError("Prusa two-object support painting cannot combine other edits.")
        if (abs(float(row.get("z_mm", 0))) > 1e-6
                or abs(float(row.get("rotation_deg", 0))) > 1e-6
                or any(abs(float(v)) > 1e-6 for v in row.get("rotation_xyz_deg", [0, 0]))
                or abs(float(row.get("scale_percent", 100))-100) > 1e-6
                or any(abs(float(v)-100) > 1e-6 for v in
                       row.get("scale_xyz_percent", [100, 100, 100]))):
            raise ValueError("Prusa independent painted objects must be upright and unscaled.")
    enforcers = (plate[painted[0]].get("support_paint") or {}).get("regions")
    if (not isinstance(enforcers, list) or not enforcers
            or any(not isinstance(region, dict) or region.get("slot") != 0
                   for region in enforcers)):
        raise ValueError("Prusa two-object support requires painted enforcer facets.")
    return painted[0]


def audit_prusa_two_object_support(data, models, *, bed_width, bed_depth):
    """Prove deposited support only in the painted object and not its neighbour."""
    if not isinstance(data, bytes) or not 0 < len(data) <= 90 * 1024 * 1024:
        raise ValueError("Invalid Prusa two-object support G-code.")
    if not isinstance(models, list) or len(models) != 2:
        raise ValueError("Prusa two-object support audit requires two models.")
    selected = validate_prusa_two_support_plate([item for item, _ in models])
    bounds = [_bounds(source, bed_width, bed_depth) for source in models]
    a, b = bounds
    if min(a[1], b[1]) > max(a[0], b[0]) + .01 and min(a[3], b[3]) > max(a[2], b[2]) + .01:
        raise ValueError("Prusa painted support object regions overlap.")
    x = y = None
    e = 0.
    relative_e = relative_xy = False
    role = ""
    counts = [0, 0]
    stationary = [0, 0]
    outside = 0
    for index, raw_line in enumerate(io.BytesIO(data)):
        if index >= 2_000_000 or len(raw_line) > 16384:
            raise ValueError("Prusa two-object support G-code exceeds audit limits.")
        try:
            line = raw_line.decode("utf-8").strip()
        except UnicodeDecodeError:
            raise ValueError("Prusa support G-code is not UTF-8.") from None
        if line.startswith(";TYPE:"):
            role = line.partition(":")[2].strip().lower()
        cmd = line.split(";", 1)[0].strip()
        if not cmd:
            continue
        op = cmd.split(None, 1)[0].upper()
        if op not in ("M82", "M83", "G90", "G91", "G92", "G0", "G00", "G1", "G01"):
            continue
        values = {name.upper(): float(value) for name, value in WORD.findall(cmd)}
        if any(not math.isfinite(value) or abs(value) > 1e9 for value in values.values()):
            raise ValueError("Prusa support coordinates are invalid.")
        if op == "M82":
            relative_e = False
        elif op == "M83":
            relative_e = True
        elif op == "G90":
            relative_xy = False
        elif op == "G91":
            relative_xy = True
        elif op == "G92":
            e = values.get("E", e)
            x = values.get("X", x)
            y = values.get("Y", y)
        else:
            old_x, old_y = x, y
            if relative_xy:
                x = x + values["X"] if x is not None and "X" in values else (
                    None if "X" in values else x)
                y = y + values["Y"] if y is not None and "Y" in values else (
                    None if "Y" in values else y)
            else:
                x = values.get("X", x)
                y = values.get("Y", y)
            if "E" not in values:
                continue
            delta = values["E"] if relative_e else values["E"] - e
            e = e + values["E"] if relative_e else values["E"]
            if op not in ("G1", "G01") or delta <= 1e-6 or role not in ROLES:
                continue
            if x is None or y is None:
                continue
            for i, (xmin, xmax, ymin, ymax, _zmin, _zmax) in enumerate(bounds):
                if not (xmin-.2 <= x <= xmax+.2 and ymin-.2 <= y <= ymax+.2):
                    continue
                if old_x is not None and old_y is not None and (
                        abs(x-old_x)+abs(y-old_y) > 1e-7):
                    if xmin-.2 <= old_x <= xmax+.2 and ymin-.2 <= old_y <= ymax+.2:
                        counts[i] += 1
                    else:
                        outside += 1
                else:
                    stationary[i] += 1
                break
            else:
                if old_x is not None and old_y is not None and (
                        abs(x-old_x)+abs(y-old_y) > 1e-7):
                    outside += 1
    if counts[selected] < 50 or counts[1-selected] != 0:
        raise ValueError("Prusa two-object support paths were not isolated to the enforcer.")
    return {
        "painted_model_index": selected,
        "painted_support_moves": counts[selected],
        "unpainted_support_moves": counts[1-selected],
        "stationary_recovery_moves": stationary,
        "outside_support_moves": outside,
    }
