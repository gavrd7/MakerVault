"""Bounded read-only spatial evidence for native Creality painted G-code.

This is deliberately an *observation*, not a model-to-G-code proof: native
slicers can relocate geometry, omit role tags or transform coordinates.
Report an unresolved status instead of inventing physical paint correctness.
"""
import io
import math
import re
import zipfile

from defusedxml import ElementTree as ET

_CORE = "{http://schemas.microsoft.com/3dmanufacturing/core/2015/02}"
_NUM = rb"[-+]?(?:\d+(?:\.\d*)?|\.\d+)"
_ARGS = re.compile(rb"(?:^|\s)([XYZE])(" + _NUM + rb")(?=\s|$)", re.I)
_TYPE = re.compile(rb"^;\s*(?:FEATURE|TYPE):\s*(.{1,60})$", re.I)
_TOOL = re.compile(rb"^T([01])(?:\s|$)", re.I)


def painted_triangle_bounds(project, attribute):
    """Get baked 3MF coordinates of triangles carrying a native paint tag."""
    if attribute not in {
            "paint_color", "paint_supports", "paint_seam", "paint_fuzzy_skin"}:
        raise ValueError("Unknown native painting attribute.")
    if not isinstance(project, bytes) or not 0 < len(project) <= 32 * 1024 * 1024:
        raise ValueError("Invalid native project bounds input.")
    try:
        with zipfile.ZipFile(io.BytesIO(project)) as archive:
            if archive.getinfo("3D/3dmodel.model").file_size > 48 * 1024 * 1024:
                raise ValueError("Native model geometry exceeds audit bound.")
            root = ET.fromstring(archive.read("3D/3dmodel.model"))
    except (KeyError, zipfile.BadZipFile, OSError) as exc:
        raise ValueError("Native paint model is unavailable.") from exc
    vertices = []
    for node in root.iter(_CORE + "vertex"):
        if len(vertices) >= 500_000:
            raise ValueError("Native paint mesh exceeds spatial audit limit.")
        try:
            point = tuple(float(node.attrib[key]) for key in ("x", "y", "z"))
        except (KeyError, ValueError, OverflowError) as exc:
            raise ValueError("Invalid native mesh coordinate.") from exc
        if not all(math.isfinite(value) for value in point):
            raise ValueError("Nonfinite native mesh coordinate.")
        vertices.append(point)
    coords = []
    painted = 0
    for triangle in root.iter(_CORE + "triangle"):
        if attribute not in triangle.attrib:
            continue
        painted += 1
        if painted > 500_000:
            raise ValueError("Too many painted native facets.")
        for key in ("v1", "v2", "v3"):
            try:
                index = int(triangle.attrib[key])
                if index < 0:
                    raise IndexError
                coords.append(vertices[index])
            except (KeyError, IndexError, ValueError) as exc:
                raise ValueError("Invalid painted triangle vertex.") from exc
    if not coords:
        raise ValueError("No native triangle bears the requested paint tag.")
    bounds = [[min(point[i] for point in coords), max(point[i] for point in coords)]
              for i in range(3)]
    return {"x_mm": [round(v, 3) for v in bounds[0]],
            "y_mm": [round(v, 3) for v in bounds[1]],
            "z_mm": [round(v, 3) for v in bounds[2]],
            "painted_triangles": painted}


def _inside(x, y, bounds, margin):
    return (bounds["x_mm"][0] - margin <= x <= bounds["x_mm"][1] + margin
            and bounds["y_mm"][0] - margin <= y <= bounds["y_mm"][1] + margin)


def spatial_deposition_cells(gcode, *, role=None, tool=None, bounds,
                             margin_mm=2.0):
    """Count deposition segments by 2mm XY/1mm Z voxel and painted XY region.

    Support is allowed below its painted underside, so Z is reported but not
    used as a hard spatial filter. The native feature marker is treated as
    advisory; missing markers and extrusion-mode uncertainty are surfaced.
    Coordinates are never returned, only anonymous voxel counts.
    """
    if (not isinstance(gcode, bytes) or len(gcode) > 64 * 1024 * 1024
            or not isinstance(bounds, dict) or
            type(margin_mm) not in (float, int) or not 0 <= margin_mm <= 10
            or role not in (None, "support", "outer_wall")
            or tool not in (None, 0, 1)):
        raise ValueError("Invalid bounded native spatial audit.")
    x = y = z = 0.0
    previous_e = 0.0
    e_mode = None
    xy_mode = "absolute"
    active_tool = None
    active_role = ""
    cells = {}
    inside_moves = outside_moves = unknown_e_moves = 0
    matching_moves = 0
    tool_changes = 0
    lines = 0
    for raw in gcode.splitlines():
        lines += 1
        if lines > 2_000_000 or len(raw) > 8192:
            raise ValueError("G-code exceeds spatial audit bounds.")
        stripped = raw.strip().upper()
        match = _TYPE.fullmatch(stripped)
        if match:
            active_role = match.group(1).decode("ascii", "replace").strip().lower()
            continue
        if stripped.startswith(b";"):
            continue
        command = stripped.split(b";", 1)[0].strip()
        selected = _TOOL.match(command)
        if selected:
            active_tool = int(selected.group(1))
            tool_changes += 1
            continue
        if command == b"M82":
            e_mode = "absolute"
            continue
        if command == b"M83":
            e_mode = "relative"
            continue
        if command == b"G90":
            xy_mode = "absolute"
            continue
        if command == b"G91":
            xy_mode = "relative"
            continue
        if command.startswith(b"G92 "):
            vals = {key.decode(): float(number) for key, number in _ARGS.findall(command[4:])}
            previous_e = vals.get("E", previous_e)
            x, y, z = (vals.get("X", x), vals.get("Y", y), vals.get("Z", z))
            continue
        if not re.match(rb"^G0?1(?:\s|$)", command):
            continue
        values = {key.decode(): float(number) for key, number in _ARGS.findall(command)}
        next_x = values.get("X", x)
        next_y = values.get("Y", y)
        next_z = values.get("Z", z)
        if xy_mode == "relative":
            next_x = x + values.get("X", 0)
            next_y = y + values.get("Y", 0)
            next_z = z + values.get("Z", 0)
        if not all(math.isfinite(v) and abs(v) <= 100_000 for v in
                   (next_x, next_y, next_z)):
            raise ValueError("Nonfinite or out-of-range G-code motion.")
        raw_e = values.get("E")
        positive = False
        if raw_e is not None:
            if not math.isfinite(raw_e) or abs(raw_e) > 100_000:
                raise ValueError("Invalid G-code extrusion position.")
            if e_mode == "relative":
                positive = raw_e > 0
            elif e_mode == "absolute":
                positive = raw_e > previous_e
                previous_e = raw_e
            else:
                unknown_e_moves += 1
        role_match = (role is None or
                      (role == "support" and "support" in active_role) or
                      (role == "outer_wall" and active_role in
                       {"outer wall", "external perimeter"}))
        if (positive and (next_x != x or next_y != y)
                and role_match and (tool is None or active_tool == tool)):
            matching_moves += 1
            mid_x, mid_y, mid_z = (x + next_x)/2, (y + next_y)/2, (z + next_z)/2
            in_region = _inside(mid_x, mid_y, bounds, margin_mm)
            if in_region:
                inside_moves += 1
            else:
                outside_moves += 1
            voxel = (math.floor(mid_x/2), math.floor(mid_y/2), math.floor(mid_z))
            if len(cells) >= 100_000 and voxel not in cells:
                raise ValueError("Native spatial audit has too many occupied voxels.")
            cells[voxel] = cells.get(voxel, 0) + 1
        x, y, z = next_x, next_y, next_z
    return {"cells": cells,
            "observed_extrusion_mode": e_mode or "unspecified",
            "matching_deposition_moves": matching_moves,
            "inside_painted_xy_moves": inside_moves,
            "outside_painted_xy_moves": outside_moves,
            "unknown_extrusion_mode_moves": unknown_e_moves,
            "observed_tool_selects": tool_changes,
            "occupied_voxel_count": len(cells)}


def spatial_comparison(painted_gcode, unpainted_gcode, bounds, *, role,
                       tool=None, margin_mm=2.0):
    """Compare voxel deposition counts while keeping individual coordinates private."""
    painted = spatial_deposition_cells(
        painted_gcode, bounds=bounds, role=role, tool=tool, margin_mm=margin_mm)
    control = spatial_deposition_cells(
        unpainted_gcode, bounds=bounds, role=role, tool=tool, margin_mm=margin_mm)
    changed_inside = changed_outside = 0
    for voxel in painted["cells"].keys() | control["cells"].keys():
        difference = abs(painted["cells"].get(voxel, 0) -
                         control["cells"].get(voxel, 0))
        cx, cy, _cz = voxel
        if _inside((cx + .5) * 2, (cy + .5) * 2, bounds, margin_mm):
            changed_inside += difference
        else:
            changed_outside += difference
    return {
        "painted_tag_bounds_mm": bounds,
        "voxel_size_mm": [2, 2, 1],
        "comparison_role": role or "all",
        "painted": {key: value for key, value in painted.items() if key != "cells"},
        "unpainted": {key: value for key, value in control.items() if key != "cells"},
        "changed_voxel_deposition_count_inside_painted_xy": changed_inside,
        "changed_voxel_deposition_count_outside_painted_xy": changed_outside,
        "spatial_effect_observed": changed_inside > 0,
        "spatial_interpretation": (
            "In-region deposition difference observed, not proof of correct paint."
            if changed_inside else
            "No in-region deposition difference detected; spatial effect not established."
        ),
        "limitations": (
            "G-code vs baked 3MF XY alignment not independently proven; "
            "coarse voxel midpoint counts, possible native rearrangement "
            "and firmware-owned extrusion. Never use for printer approval."
        ),
    }
