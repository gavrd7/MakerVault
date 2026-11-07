"""Bounded STL shape validation before feeding untrusted models to a slicer.

Syntax validation is not a mesh repair or geometry safety guarantee.
The isolated worker remains the mandatory execution boundary.
"""
import math
import re
import struct


MAX_STL_TRIANGLES = 500_000
MAX_COORDINATE_MM = 1_000_000.0


class StlValidationError(ValueError):
    pass


_NUMBER = r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[Ee][+-]?\d+)?"
_VERTEX = re.compile(r"^vertex\s+(" + _NUMBER + r")\s+(" + _NUMBER + r")\s+(" + _NUMBER + r")\s*$", re.I)
_FACET = re.compile(r"^facet\s+normal\s+" + _NUMBER + r"\s+" + _NUMBER + r"\s+" + _NUMBER + r"\s*$", re.I)


def validate_stl(data: bytes) -> dict:
    if not isinstance(data, bytes) or not data:
        raise StlValidationError("An STL model is required.")
    if len(data) >= 84:
        triangles = struct.unpack_from("<I", data, 80)[0]
        expected = 84 + 50 * triangles
        if expected == len(data) and 0 < triangles <= MAX_STL_TRIANGLES:
            finite_vertices = 0
            for record in struct.iter_unpack("<12fH", memoryview(data)[84:]):
                if not all(math.isfinite(value) and abs(value) <= MAX_COORDINATE_MM for value in record[:12]):
                    raise StlValidationError("STL contains non-finite or extreme coordinates.")
                if any(value != 0 for value in record[3:12]):
                    finite_vertices += 1
            if not finite_vertices:
                raise StlValidationError("STL contains no nonzero geometry.")
            return {"format": "binary", "triangles": triangles}
    # Enforce ASCII STL nesting, not just counts of facets and vertices.
    # Malformed or truncated facet boundaries must never be passed to Orca.
    if len(data) > 32 * 1024 * 1024:
        raise StlValidationError("STL exceeds the model size limit.")
    try:
        content = data.decode("ascii")
    except UnicodeDecodeError:
        raise StlValidationError("STL is not valid binary or ASCII.") from None
    lines = (line.strip() for line in content.splitlines() if line.strip())
    first = next(lines, "")
    if not first.lower().startswith("solid"):
        raise StlValidationError("Invalid ASCII STL header.")
    state = "facet"
    faces = 0
    for line in lines:
        if len(line) > 4096:
            raise StlValidationError("STL contains an excessively long line.")
        lowered = line.lower()
        if state == "facet" and lowered.startswith("endsolid"):
            if not faces:
                raise StlValidationError("STL has no triangles.")
            state = "done"
            continue
        if state == "facet" and (match := _FACET.fullmatch(line)):
            if not all(math.isfinite(float(n)) and abs(float(n)) <= MAX_COORDINATE_MM for n in match.groups()):
                raise StlValidationError("STL normal is not finite.")
            state = "outer"
        elif state == "outer" and lowered == "outer loop":
            state = "vertex1"
        elif state in {"vertex1", "vertex2", "vertex3"} and (match := _VERTEX.fullmatch(line)):
            if not all(math.isfinite(float(n)) and abs(float(n)) <= MAX_COORDINATE_MM for n in match.groups()):
                raise StlValidationError("STL has non-finite or extreme coordinates.")
            state = {"vertex1": "vertex2", "vertex2": "vertex3", "vertex3": "endloop"}[state]
        elif state == "endloop" and lowered == "endloop":
            state = "endfacet"
        elif state == "endfacet" and lowered == "endfacet":
            faces += 1
            if faces > MAX_STL_TRIANGLES:
                raise StlValidationError("STL triangle count exceeds limit.")
            state = "facet"
        else:
            raise StlValidationError("Malformed ASCII STL facet structure.")
    if state != "done":
        raise StlValidationError("ASCII STL ended before a complete solid was closed.")
    return {"format": "ascii", "triangles": faces}
