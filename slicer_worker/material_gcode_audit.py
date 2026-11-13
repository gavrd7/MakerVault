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
            mx = re.search(r"(?:^|\\s)X([-+]?(?:\\d+(?:\\.\\d*)?|\\.\\d+))(?=\\s|$)", code)
            my = re.search(r"(?:^|\\s)Y([-+]?(?:\\d+(?:\\.\\d*)?|\\.\\d+))(?=\\s|$)", code)
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
