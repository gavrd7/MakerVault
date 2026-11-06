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
    # Strict ASCII fallback; reject malformed binary with misleading 'solid'
    # header by requiring every line to match the ASCII STL grammar.
    try:
        content = data.decode("ascii")
    except UnicodeDecodeError:
        raise StlValidationError("STL is not valid binary or ASCII.") from None
    lines = content.splitlines()
    if not lines or not lines[0].strip().lower().startswith("solid"):
        raise StlValidationError("Invalid ASCII STL header.")
    faces = 0
    vertices = 0
    for line in lines[1:]:
        line = line.strip()
        if not line:
            continue
        if _FACET.fullmatch(line):
            faces += 1
            if faces > MAX_STL_TRIANGLES:
                raise StlValidationError("STL triangle count exceeds limit.")
        elif (match := _VERTEX.fullmatch(line)):
            vertices += 1
            if not all(math.isfinite(float(x)) and abs(float(x)) <= MAX_COORDINATE_MM for x in match.groups()):
                raise StlValidationError("STL contains non-finite or extreme coordinates.")
        elif line.lower().startswith("endsolid"):
            continue
        elif line.lower() in {"outer loop", "endloop", "endfacet"}:
            continue
        else:
            raise StlValidationError("Invalid ASCII STL structure.")
    if not faces or vertices != faces * 3:
        raise StlValidationError("STL face and vertex counts do not agree.")
    return {"format": "ascii", "triangles": faces}
