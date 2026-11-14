"""Observe exact native tool selections and material deposition in worker output.

Only a bounded acceptance check, never proof of printer firmware compatibility.
A profile's toolchange macro is not interpreted or executed by this module.
"""
import io
import re
import zipfile
from xml.etree import ElementTree as ET

from .runner import WorkerError

TOOL = re.compile(r"^T(\d{1,2})(?:\s|$)", re.I)
MOVE = re.compile(r"^G0?[01](?:\s|$)", re.I)
E_AXIS = re.compile(r"(?:^|\s)E([-+]?(?:\d+(?:\.\d*)?|\.\d+))(?:\s|$)", re.I)
XY = re.compile(r"(?:^|\s)[XY][-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:\s|$)", re.I)


def expected_native_tools(project_bytes):
    with zipfile.ZipFile(io.BytesIO(project_bytes)) as archive:
        root = ET.fromstring(archive.read("Metadata/model_settings.config"))
    tools = []
    for item in root.findall("object"):
        entries = [e.attrib.get("value") for e in item.findall("metadata")
                   if e.attrib.get("key") == "extruder"]
        if len(entries) != 1 or not entries[0].isdecimal():
            raise WorkerError("Multi-filament 3MF object lacks an extruder.")
        tools.append(int(entries[0]) - 1)
    return set(tools)


def verify_multi_material_output(raw_gcode, expected):
    if not isinstance(raw_gcode, bytes) or len(raw_gcode) > 64 * 1024 * 1024:
        raise WorkerError("Invalid multi-material output.")
    if not isinstance(expected, set) or len(expected) < 2:
        raise WorkerError("Missing multi-material verification targets.")
    try:
        text = raw_gcode.decode("utf-8")
    except UnicodeDecodeError:
        raise WorkerError("Multi-material G-code is not valid UTF-8.") from None
    active = None
    absolute = True
    extrusion = {}
    deposits = set()
    selected = set()
    for raw in text.splitlines():
        line = raw.split(";", 1)[0].strip().upper()
        match = TOOL.fullmatch(line)
        if match:
            active = int(match.group(1))
            selected.add(active)
            continue
        command = line.split(None, 1)[0] if line else ""
        if command == "M82":
            absolute = True
        elif command == "M83":
            absolute = False
        elif command == "G92" and active is not None:
            match = E_AXIS.search(line[3:])
            if match:
                extrusion[active] = float(match.group(1))
        elif active is not None and MOVE.match(line):
            match = E_AXIS.search(line)
            if match:
                value = float(match.group(1))
                before = extrusion.get(active, 0)
                if XY.search(line) and (
                        (absolute and value > before + 1e-6)
                        or (not absolute and value > 1e-6)):
                    deposits.add(active)
                if absolute:
                    extrusion[active] = value
    if not expected.issubset(selected) or not expected.issubset(deposits):
        raise WorkerError("Native output lacks required filament changes and deposited extrusion.")
    return True

def verify_two_object_tool_regions(raw_gcode, *, left_tool=0, right_tool=1):
    """Acceptance-only proof for fixed separated 20mm cubes at X=75/145.

    Require substantial deposition in each model's X/Y region by its
    requested tool. Extrusion in a purge tower alone cannot satisfy this.
    This is intentionally fixture-specific, never a general project parser.
    """
    if not isinstance(raw_gcode, bytes) or len(raw_gcode) > 64 * 1024 * 1024:
        raise WorkerError("Invalid native material fixture output.")
    last_x = last_y = 0.0
    active = None
    absolute = True
    previous_e = {}
    hits = [0, 0]
    mismatches = [0, 0]
    for raw in raw_gcode.decode("utf-8", "replace").splitlines():
        code = raw.split(";", 1)[0].strip().upper()
        selection = TOOL.fullmatch(code)
        if selection:
            active = int(selection.group(1))
            continue
        operation = code.split(None, 1)[0] if code else ""
        if operation == "M82":
            absolute = True
        elif operation == "M83":
            absolute = False
        elif operation == "G92" and active is not None:
            entry = E_AXIS.search(code[3:])
            if entry:
                previous_e[active] = float(entry.group(1))
        elif MOVE.match(code):
            mx = re.search(r"(?:^|\s)X([-+]?(?:\d+(?:\.\d*)?|\.\d+))(?=\s|$)", code)
            my = re.search(r"(?:^|\s)Y([-+]?(?:\d+(?:\.\d*)?|\.\d+))(?=\s|$)", code)
            if mx:
                last_x = float(mx.group(1))
            if my:
                last_y = float(my.group(1))
            match = E_AXIS.search(code)
            if match and active is not None:
                value = float(match.group(1))
                prior = previous_e.get(active, 0)
                depositing = (value > prior + 1e-6) if absolute else value > 1e-6
                if absolute:
                    previous_e[active] = value
                if depositing and (mx or my):
                    region = (0 if 64 <= last_x <= 86 and 99 <= last_y <= 121 else
                              1 if 134 <= last_x <= 156 and 99 <= last_y <= 121 else None)
                    if region is not None:
                        if active == (left_tool if region == 0 else right_tool):
                            hits[region] += 1
                        else:
                            mismatches[region] += 1
    if min(hits) < 20 or any(mismatches):
        raise WorkerError("Native multi-tool G-code does not match the expected model/tool regions.")
    return {"left_tool_deposits": hits[0], "right_tool_deposits": hits[1]}


def summarize_k2_fixture_changeovers(raw_gcode):
    """Offline evidence for fixed two-cube test, NOT a physical K2 approval.

    Count tool selections and deposition away from the two model regions;
    distinguish XY deposition from stationary purge. These observations
    cannot prove actual CFS mechanics, nozzle wiping or colour cleanliness.
    """
    if not isinstance(raw_gcode, bytes) or not raw_gcode or len(raw_gcode) > 64 * 1024 * 1024:
        raise WorkerError("Invalid bounded two-tool fixture G-code.")
    try:
        lines = raw_gcode.decode("utf-8").splitlines()
    except UnicodeDecodeError:
        raise WorkerError("Two-tool fixture G-code is not plain UTF-8.") from None
    # Only analyse G90/M82 or M83 absolute XY fixture output. Reject
    # relative XY to avoid inventing positions.
    active = None
    relative_e = False
    absolute_xyz = True
    prev_e = {}
    x = y = 0.0
    changed = 0
    selections = set()
    outside_xy = {}
    stationary_e = {}
    feature_counts = {}
    feature = ""
    for raw in lines:
        if raw.lstrip().startswith(";"):
            comment = raw.lstrip()[1:].strip()
            if comment.upper().startswith(("TYPE:", "FEATURE:")):
                feature = comment.split(":", 1)[1].strip().lower()[:80]
            continue
        line = raw.split(";", 1)[0].strip().upper()
        if not line:
            continue
        tool = TOOL.fullmatch(line)
        if tool:
            next_tool = int(tool.group(1))
            if active is not None and active != next_tool:
                changed += 1
            active = next_tool
            selections.add(active)
            continue
        command = line.split(None, 1)[0]
        if command == "G90":
            absolute_xyz = True
        elif command == "G91":
            absolute_xyz = False
        elif command == "M82":
            relative_e = False
        elif command == "M83":
            relative_e = True
        elif command == "G92" and active is not None:
            entry = E_AXIS.search(line)
            if entry:
                prev_e[active] = float(entry.group(1))
        elif MOVE.match(line) and active is not None:
            ex = E_AXIS.search(line)
            if not ex:
                # Travel coordinates are still important to locate stationary
                # purging and subsequent XY extrusion.
                coords = re.findall(r"(?:^|\s)([XY])([-+]?(?:\d+(?:\.\d*)?|\.\d+))(?=\s|$)", line)
                for axis, value in coords:
                    if not absolute_xyz:
                        raise WorkerError("Relative XY is unsupported in the K2 fixture auditor.")
                    if axis == "X":
                        x = float(value)
                    else:
                        y = float(value)
                continue
            value = float(ex.group(1))
            previous = prev_e.get(active, 0.0)
            deposition = value if relative_e else value - previous
            if not relative_e:
                prev_e[active] = value
            coords = re.findall(r"(?:^|\s)([XY])([-+]?(?:\d+(?:\.\d*)?|\.\d+))(?=\s|$)", line)
            if coords and not absolute_xyz:
                raise WorkerError("Relative XY is unsupported in the K2 fixture auditor.")
            for axis, number in coords:
                if axis == "X":
                    x = float(number)
                else:
                    y = float(number)
            if deposition <= 1e-6:
                continue
            if not coords:
                stationary_e[active] = stationary_e.get(active, 0) + 1
                continue
            left = 64 <= x <= 86 and 99 <= y <= 121
            right = 134 <= x <= 156 and 99 <= y <= 121
            if not left and not right:
                outside_xy[active] = outside_xy.get(active, 0) + 1
                if feature:
                    feature_counts[feature] = feature_counts.get(feature, 0) + 1
    return {
        "tool_switches": changed,
        "selected_tools": sorted(selections),
        "outside_model_deposition_moves": {str(k): v for k, v in sorted(outside_xy.items())},
        "stationary_extrusion_moves": {str(k): v for k, v in sorted(stationary_e.items())},
        "outside_deposition_features": dict(sorted(feature_counts.items())),
    }


def verify_k2_fixture_purge_tower_evidence(raw_gcode):
    """Fail the *offline K2 two-cube fixture* without real tower toolpaths.

    The pinned Orca acceptance requires tools to switch repeatedly, each to
    extrude outside both model footprints, and the native Orca output to
    label a substantial number of those moves as prime-tower deposition.
    This does not validate CFS firmware commands or physical purge quality.
    """
    evidence = summarize_k2_fixture_changeovers(raw_gcode)
    per_tool = evidence["outside_model_deposition_moves"]
    if (evidence["selected_tools"] != [0, 1]
            or evidence["tool_switches"] < 2
            or int(per_tool.get("0", 0)) < 20
            or int(per_tool.get("1", 0)) < 20
            or evidence["outside_deposition_features"].get("prime tower", 0) < 20):
        raise WorkerError(
            "K2 native fixture lacks verified multi-tool prime-tower deposition evidence.")
    evidence["k2_prime_tower_evidence_verified"] = True
    return evidence
