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
