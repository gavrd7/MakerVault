"""Safe, read-only STL bounding-box inspection for the Slicer workbench.

Separate from worker execution: this runs inside the existing Django API and
never runs a slicer, loads external files or infers a printer's usable volume.
A bounding box is only a geometric observation, not sliceability evidence.
"""
import math
import re
import struct

MAX_INSPECTION_BYTES = 32 * 1024 * 1024
MAX_TRIANGLES = 500_000
COORD_LIMIT_MM = 1_000_000
NUMBER = r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?"
VERTEX = re.compile(r"^vertex\s+("+NUMBER+r")\s+("+NUMBER+r")\s+("+NUMBER+r")$", re.I)
FACET = re.compile(r"^facet\s+normal\s+("+NUMBER+r")\s+("+NUMBER+r")\s+("+NUMBER+r")$", re.I)


class MeshInspectionError(ValueError):
    pass


def inspect_stl(raw):
    if not isinstance(raw, bytes) or not raw or len(raw) > MAX_INSPECTION_BYTES:
        raise MeshInspectionError("STL is empty or exceeds the safe inspection limit.")
    lower = [float("inf")] * 3
    upper = [float("-inf")] * 3

    def vertex(values):
        for axis, value in enumerate(values):
            value = float(value)
            if not math.isfinite(value) or abs(value) > COORD_LIMIT_MM:
                raise MeshInspectionError("STL has non-finite or extreme coordinates.")
            lower[axis] = min(lower[axis], value)
            upper[axis] = max(upper[axis], value)

    if len(raw) >= 84:
        n = struct.unpack_from("<I", raw, 80)[0]
        if 0 < n <= MAX_TRIANGLES and 84 + 50 * n == len(raw):
            for record in struct.iter_unpack("<12fH", raw[84:]):
                if not all(math.isfinite(x) and abs(x) <= COORD_LIMIT_MM for x in record[:3]):
                    raise MeshInspectionError("STL has invalid face normals.")
                for offset in (3, 6, 9):
                    vertex(record[offset:offset + 3])
            if lower == upper:
                raise MeshInspectionError("STL contains no printable dimensions.")
            return _summary("binary", n, lower, upper)
    try:
        text = raw.decode("ascii")
    except UnicodeDecodeError:
        raise MeshInspectionError("STL must be valid binary or ASCII.") from None
    lines = (line.strip() for line in text.splitlines() if line.strip())
    if not next(lines, "").lower().startswith("solid"):
        raise MeshInspectionError("STL header is invalid.")
    state, triangles = "facet", 0
    for line in lines:
        if len(line) > 4096:
            raise MeshInspectionError("STL line exceeds inspection limit.")
        key = line.lower()
        if state == "facet" and key.startswith("endsolid"):
            if triangles < 1:
                raise MeshInspectionError("STL has no triangles.")
            state = "done"
        elif state == "facet" and (match := FACET.fullmatch(line)):
            for item in match.groups():
                x = float(item)
                if not math.isfinite(x) or abs(x) > COORD_LIMIT_MM:
                    raise MeshInspectionError("STL normal is invalid.")
            state = "outer"
        elif state == "outer" and key == "outer loop":
            state = "v1"
        elif state in {"v1", "v2", "v3"} and (match := VERTEX.fullmatch(line)):
            vertex(match.groups())
            state = {"v1": "v2", "v2": "v3", "v3": "endloop"}[state]
        elif state == "endloop" and key == "endloop":
            state = "endfacet"
        elif state == "endfacet" and key == "endfacet":
            triangles += 1
            if triangles > MAX_TRIANGLES:
                raise MeshInspectionError("STL triangle count exceeds limit.")
            state = "facet"
        else:
            raise MeshInspectionError("STL facet syntax is invalid.")
    if state != "done" or lower == upper:
        raise MeshInspectionError("STL is incomplete or contains no printable dimensions.")
    return _summary("ascii", triangles, lower, upper)


def _summary(kind, triangles, lower, upper):
    return {
        "format": kind,
        "triangles": triangles,
        "bounds_mm": {"min": [round(x, 3) for x in lower],
                      "max": [round(x, 3) for x in upper]},
        "size_mm": [round(high - low, 3) for low, high in zip(lower, upper)],
        "printer_fit": "not_checked",
    }
