"""Strict observational audit of native G-code tool selection and extrusion.

This is evidence for real binary acceptance, NOT a firmware validator.
T0/T1 commands can select virtual filaments or independent heads depending on
printer topology. Seeing them never authorises uploading/starting a print.
"""
import re
from collections import Counter

TOOL = re.compile(r"^T(\d{1,2})(?:\s|$)", re.I)
AXIS_E = re.compile(r"(?:^|\s)E([-+]?(?:\d+(?:\.\d*)?|\.\d+))(?:\s|$)", re.I)
MOVE = re.compile(r"^G(?:0|1|00|01)(?:\s|$)", re.I)
XY_MOVE = re.compile(r"(?:^|\s)[XY][-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:\s|$)", re.I)
MAX_TOOLS = 16
MAX_GCODE_LINES = 2_000_000


class MaterialGcodeAuditError(ValueError):
    pass


def audit_native_tool_usage(gcode, *, expected_tools):
    """Return observed zero-based tools with positive extrusion move counts.

    Fail if expected tools have no explicit selection and extrusion evidence.
    The caller separately verifies the exact pinned binary, profile, topology,
    material/purge sequence and the target printer's firmware semantics.
    """
    if not isinstance(gcode, str) or not isinstance(expected_tools, (set, tuple, list)):
        raise MaterialGcodeAuditError("Invalid tool audit input.")
    if not expected_tools or any(
        isinstance(tool, bool) or not isinstance(tool, int) or not 0 <= tool < MAX_TOOLS
        for tool in expected_tools
    ):
        raise MaterialGcodeAuditError("Invalid expected tool indices.")
    expected = set(expected_tools)
    if len(expected) < 2:
        raise MaterialGcodeAuditError("This audit requires a multi-tool fixture.")
    if len(gcode) > 90 * 1024 * 1024:
        raise MaterialGcodeAuditError("G-code exceeds audit limits.")
    counts = Counter()
    changes = []
    tool = None
    absolute_e = True
    last_e = {}
    for number, raw in enumerate(gcode.splitlines(), start=1):
        if number > MAX_GCODE_LINES:
            raise MaterialGcodeAuditError("Too many G-code lines to audit.")
        line = raw.split(";", 1)[0].strip().upper()
        if not line:
            continue
        selection = TOOL.fullmatch(line) if line.startswith("T") else None
        if selection:
            tool = int(selection.group(1))
            if tool >= MAX_TOOLS:
                raise MaterialGcodeAuditError("Tool index exceeds the audit limit.")
            changes.append(tool)
            continue
        command = line.split(None, 1)[0]
        if command == "M82":
            absolute_e = True
        elif command == "M83":
            absolute_e = False
        elif command == "G92":
            value = AXIS_E.search(line[3:])
            if value and tool is not None:
                last_e[tool] = float(value.group(1))
        elif MOVE.match(line):
            value = AXIS_E.search(line)
            if value and tool is not None:
                extrusion = float(value.group(1))
                previous = last_e.get(tool, 0.0)
                positive = extrusion > previous + 1e-6 if absolute_e else extrusion > 1e-6
                if positive and XY_MOVE.search(line):
                    counts[tool] += 1
                if absolute_e:
                    last_e[tool] = extrusion
    observed = set(changes)
    if not expected.issubset(observed):
        raise MaterialGcodeAuditError("Generated G-code omitted a required tool selection.")
    if any(counts[tool] <= 0 for tool in expected):
        raise MaterialGcodeAuditError("Generated G-code omitted extrusion on an assigned tool.")
    return {
        "selected_tools": tuple(sorted(observed)),
        "selection_sequence": tuple(changes),
        "extruding_moves": {tool: counts[tool] for tool in sorted(counts)},
        "has_multiple_tools": len(observed) >= 2,
    }
