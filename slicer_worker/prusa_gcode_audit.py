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


def run_prusa_painted_with_numeric_recheck(
        runner, binary, workdir, *, timeout_seconds, max_bytes):
    """Bounded offline-only recovery from intermittent native coordinate overflow.

    The pinned Prusa 2.9.7 MMU painted-facet route has intermittently emitted
    Y coordinates around 1e13. Never repair or sanitize those bytes. Discard
    the entire file, invoke a new isolated native CLI process at most twice,
    and require the original strict numeric audit on every candidate.
    Downstream spatial/tool/purge audits remain independently mandatory.
    No unpainted engine or hardware submission uses this helper.
    """
    if not isinstance(max_bytes, int) or max_bytes < 2000:
        raise WorkerError("Invalid Prusa G-code output budget.")
    output = workdir / "output.gcode"
    for attempt in range(3):
        if attempt:
            # A failed attempt may leave corrupt or partial output behind.
            # Unlink before running again; never accidentally inspect stale
            # G-code if the native subprocess fails to create a new file.
            output.unlink(missing_ok=True)
        receipt = runner(binary, workdir, timeout_seconds=timeout_seconds)
        try:
            data = output.read_bytes()
        except OSError as exc:
            raise WorkerError("Native Prusa output could not be read.") from exc
        if not data or len(data) > max_bytes:
            raise WorkerError("Generated G-code exceeded the output size limit.")
        try:
            audit_prusa_positive_e(data)
        except WorkerError as exc:
            if (str(exc) == "Prusa native G-code contains invalid coordinates."
                    and attempt < 2):
                continue
            raise
        return receipt, data
    raise WorkerError("Prusa native G-code coordinates could not be verified.")
