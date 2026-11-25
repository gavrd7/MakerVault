"""Prusa-native painted facet serialization for candidate offline 3MF acceptance.

PrusaSlicer 2.9.7 expects namespaced triangle attributes and painting
version metadata, not Orca's unqualified `paint_supports` keys. Reuse only
MakerVault's exact, fingerprint-checked geometric patch splitter; never
allow browser XML or external project archives into this encoder.
"""
import struct
import re
import math

from .slicer_plate_3mf import _triangles
from .slicer_native_support_paint import (
    MAX_NATIVE_PAINT_TRIANGLES, native_combined_paint_triangles,
)

NATIVE_ATTRIBUTES = {
    "paint_supports": "slic3rpe:custom_supports",
    "paint_seam": "slic3rpe:custom_seam",
    "paint_fuzzy_skin": "slic3rpe:fuzzy_skin",
}
HEADERS = {
    "support_paint": "slic3rpe:FdmSupportsPaintingVersion",
    "seam_paint": "slic3rpe:SeamPaintingVersion",
    "fuzzy_skin_paint": "slic3rpe:FuzzySkinPaintingVersion",
}


def native_prusa_painted_stl(item, source):
    """Return (binary STL, per-face Prusa attribute dicts, required headers).

    Every returned tag belongs to a mesh facet. No paint channels are silently
    discarded; support/seam may use 4 or 8, while fuzzy uses painted-only 4.
    """
    channels = {
        key for key in HEADERS
        if isinstance(item.get(key), dict) and item[key].get("regions")
    }
    if not channels:
        return source, None, frozenset()
    original = list(_triangles(source))
    painted = native_combined_paint_triangles(
        original, item.get("support_paint"), item.get("seam_paint"),
        item.get("fuzzy_skin_paint"))
    if not 0 < len(painted) <= MAX_NATIVE_PAINT_TRIANGLES:
        raise ValueError("Prusa painted mesh exceeds native triangle limit.")
    binary = bytearray(b"MakerVault PrusaSlicer painted facets".ljust(80, b"\0"))
    binary.extend(struct.pack("<I", len(painted)))
    attributes = []
    seen = set()
    for triangle, tags in painted:
        try:
            flat = [float(coordinate) for vertex in triangle for coordinate in vertex]
            binary.extend(struct.pack("<12fH", 0, 0, 0, *flat, 0))
        except (TypeError, ValueError, OverflowError, struct.error):
            raise ValueError("Prusa painted triangle has invalid geometry.") from None
        mapped = {NATIVE_ATTRIBUTES[name]: value for name, value in tags.items()}
        if any(value not in ("4", "8") for value in mapped.values()):
            raise ValueError("Prusa painted facet state is unsupported.")
        if mapped.get("slic3rpe:fuzzy_skin") == "8":
            raise ValueError("Prusa fuzzy skin must use painted-only state.")
        seen.update(tags)
        attributes.append(mapped)
    required = {HEADERS[key] for key in channels}
    if set(NATIVE_ATTRIBUTES[name] for name in seen) != set(
            NATIVE_ATTRIBUTES[name] for name in NATIVE_ATTRIBUTES
            if (name == "paint_supports" and "support_paint" in channels)
            or (name == "paint_seam" and "seam_paint" in channels)
            or (name == "paint_fuzzy_skin" and "fuzzy_skin_paint" in channels)):
        raise ValueError("Prusa facet exporter dropped a painted channel.")
    return bytes(binary), attributes, frozenset(required)


_WORD = re.compile(r"([XYZE])([-+]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+))", re.I)


def audit_prusa_support_enforcer_gcode(data):
    """Require real positive-E XY moves labelled as native Prusa supports.

    A valid 3MF support enforcer which produces zero support extrusion is
    *not* evidence that the desired support was actually sliced. Refuse
    persisting such an offline G-code job rather than silently discarding it.
    """
    if not isinstance(data, bytes) or not 0 < len(data) <= 90 * 1024 * 1024:
        raise ValueError("Invalid Prusa support G-code.")
    try:
        lines = data.decode("utf-8").splitlines()
    except UnicodeDecodeError:
        raise ValueError("Prusa support G-code is not UTF-8.") from None
    role = ""
    relative = False
    e = 0.
    moves = 0
    total = 0.
    for index, line in enumerate(lines):
        if index > 2_000_000:
            raise ValueError("Prusa support audit line limit exceeded.")
        if line.startswith(";TYPE:"):
            role = line.partition(":")[2].strip().lower()
        cmd = line.split(";", 1)[0].strip()
        if not cmd:
            continue
        opcode = cmd.split(None, 1)[0].upper()
        if opcode not in ("M82", "M83", "G92", "G0", "G00", "G1", "G01"):
            continue
        words = {key.upper(): float(value) for key, value in _WORD.findall(cmd)}
        if opcode == "M82":
            relative = False
        elif opcode == "M83":
            relative = True
        elif opcode == "G92":
            e = words.get("E", e)
        elif opcode in ("G1", "G01") and "E" in words:
            delta = words["E"] if relative else words["E"] - e
            e = e + words["E"] if relative else words["E"]
            if (delta > 1e-6 and math.isfinite(delta) and
                    ("X" in words or "Y" in words) and "support" in role):
                total += delta
                moves += 1
    if moves < 2 or total <= .01:
        raise ValueError("Prusa painted support enforcers produced no native support paths.")
    return {"support_extrusion_moves": moves, "support_extrusion_e_mm": round(total, 3)}
