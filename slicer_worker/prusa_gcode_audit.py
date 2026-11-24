"""Bounded final acceptance for PrusaSlicer text-only single-material G-code.

The generic worker's output byte cap still applies. This additional
Prusa-only check proves there are actual planar extrusions, not merely a
success exit code or an empty generated header. It never processes user
profile strings or returns G-code text to logs.
"""
from __future__ import annotations

import math
import re

from .runner import WorkerError

MAX_LINE_BYTES = 16384
MAX_GCODE_BYTES = 64 * 1024 * 1024
# Only read known simple G-code words; reject nonfinite numeric E values.
WORD = re.compile(r"(?:^|\s)([XYZE])\s*([-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[Ee][-+]?\d+)?)", re.I)


def audit_prusa_positive_e(data: bytes) -> dict[str, int]:
    if not isinstance(data, bytes) or not 2000 <= len(data) <= MAX_GCODE_BYTES:
        raise WorkerError("Prusa native G-code is missing or exceeds its limit.")
    if b"\x00" in data:
        raise WorkerError("Prusa native G-code must be plain text.")
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        raise WorkerError("Prusa native G-code must use UTF-8 text.") from None
    relative = False  # Prusa may switch to M83 for relative E.
    previous_e = 0.0
    positive = 0
    layers = 0
    for line in text.splitlines():
        if len(line) > MAX_LINE_BYTES:
            raise WorkerError("Prusa native G-code line is too long.")
        instruction = line.split(";", 1)[0].strip()
        if not instruction:
            continue
        opcode = instruction.split(None, 1)[0].upper()
        if opcode == "M82":
            relative = False
        elif opcode == "M83":
            relative = True
        elif opcode == "G92":
            for key, val in WORD.findall(instruction):
                if key.upper() == "E":
                    previous_e = float(val)
        elif opcode in {"G0", "G00", "G1", "G01"}:
            pairs = [(key.upper(), float(val)) for key, val in WORD.findall(instruction)]
            if any(not math.isfinite(val) or abs(val) > 1e9 for _, val in pairs):
                raise WorkerError("Prusa native G-code contains invalid coordinates.")
            params = dict(pairs)
            if "Z" in params and "X" not in params and "Y" not in params:
                layers += 1
            if "E" not in params:
                continue
            amount = params["E"] if relative else params["E"] - previous_e
            # Relative moves still advance the extruder's position. Preserve
            # that reference when a file switches back to absolute E (M82).
            previous_e = previous_e + params["E"] if relative else params["E"]
            if amount > 0.00001 and ("X" in params or "Y" in params):
                positive += 1
    if positive < 1:
        raise WorkerError("Prusa native G-code contains insufficient real extrusion.")
    return {"positive_e_moves": positive, "z_moves": layers}
