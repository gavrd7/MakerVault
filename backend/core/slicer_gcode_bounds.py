"""Fail-closed XY extrusion bounds check for experimental native multi-STL G-code.

This checks nozzle extrusion coordinates, not just the presence of T0/T1.
It does not establish firmware safety, CFS semantics or project placement.
"""
import math
import re

from .slicer_resource_budget import gcode_transport_budget, memory_budget

MOVE = re.compile(r"^G0?([01])(?:\s|$)", re.I)
AXIS = re.compile(r"(?:^|\s)([XYE])([-+]?(?:\d+(?:\.\d*)?|\.\d+))(?:\s|$)", re.I)
MAX_LINES = 2_000_000


class GcodeExtrusionBoundsError(ValueError):
    pass


def audit_extrusion_xy_bounds(gcode, *, width, depth, tolerance=0.05):
    if (not isinstance(gcode, str) or len(gcode.encode("utf-8")) > gcode_transport_budget() or
            not all(isinstance(v, (float, int)) and not isinstance(v, bool) and
                    math.isfinite(v) for v in (width, depth, tolerance)) or
            not 1 <= width <= 1000 or not 1 <= depth <= 1000 or
            not 0 <= tolerance <= 0.1):
        raise GcodeExtrusionBoundsError("Cannot establish trusted plate bounds.")
    # Track XY and E independently, including G92 re-zero and relative moves.
    x = y = 0.0
    e = 0.0
    xyz_absolute = True
    e_absolute = True
    extrusions = 0
    line_budget = memory_budget(
        reserve_bytes=256 * 1024 * 1024, expansion_factor=128)
    if line_budget is None:
        line_budget = MAX_LINES
    for line_num, raw in enumerate(gcode.splitlines(), 1):
        if line_num > line_budget:
            raise GcodeExtrusionBoundsError("G-code exceeds bounds audit limit.")
        line = raw.split(";", 1)[0].strip().upper()
        if not line:
            continue
        command = line.split(None, 1)[0]
        if command == "G90":
            xyz_absolute = True
            continue
        if command == "G91":
            xyz_absolute = False
            continue
        if command == "M82":
            e_absolute = True
            continue
        if command == "M83":
            e_absolute = False
            continue
        if command == "G92":
            values = {axis: float(raw_value) for axis, raw_value in AXIS.findall(line)}
            x, y, e = values.get("X", x), values.get("Y", y), values.get("E", e)
            continue
        if not MOVE.match(line):
            continue
        values = {axis: float(raw_value) for axis, raw_value in AXIS.findall(line)}
        if not all(math.isfinite(v) for v in values.values()):
            raise GcodeExtrusionBoundsError("Non-finite G-code coordinate.")
        nx = (values["X"] if xyz_absolute else x + values["X"]) if "X" in values else x
        ny = (values["Y"] if xyz_absolute else y + values["Y"]) if "Y" in values else y
        ne = (values["E"] if e_absolute else e + values["E"]) if "E" in values else e
        positive = "E" in values and (ne > e + 1e-6 if e_absolute else values["E"] > 1e-6)
        if positive and ("X" in values or "Y" in values):
            extrusions += 1
            if (min(x, nx) < -tolerance or max(x, nx) > width + tolerance or
                    min(y, ny) < -tolerance or max(y, ny) > depth + tolerance):
                raise GcodeExtrusionBoundsError(
                    "Generated G-code extrudes outside the native printable rectangle.")
        x, y, e = nx, ny, ne
    if extrusions == 0:
        raise GcodeExtrusionBoundsError("No bounded XY extrusion moves found.")
    return {"extrusion_moves_checked": extrusions, "width": width, "depth": depth}
