"""Observe exact native tool selections and material deposition in worker output.

Only a bounded acceptance check, never proof of printer firmware compatibility.
A profile's toolchange macro is not interpreted or executed by this module.
"""
import io
import math
import re
import zipfile
from xml.etree import ElementTree as ET

from .runner import WorkerError

TOOL = re.compile(r"^T(\d{1,2})(?:\s|$)", re.I)
MOVE = re.compile(r"^G0?[01](?:\s|$)", re.I)
E_AXIS = re.compile(r"(?:^|\s)E([-+]?(?:\d+(?:\.\d*)?|\.\d+))(?:\s|$)", re.I)
XY = re.compile(r"(?:^|\s)[XY][-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:\s|$)", re.I)


def expected_native_tools(project_bytes):
    """Derive every used tool, including colours painted onto a single object.

    Native Orca object extruder metadata is one-based; 3MF paint_color facet
    states identify zero-based palette slots: 4 -> 0, 8 -> 1, 0C -> 2, etc.
    The worker has already validated the 3MF and its native tool palette
    before this audit is called. An invalid or absent mapping still fails
    closed rather than silently omitting a painted colour.
    """
    with zipfile.ZipFile(io.BytesIO(project_bytes)) as archive:
        manifest = ET.fromstring(archive.read("Metadata/model_settings.config"))
        tools = set()
        for item in manifest.findall("object"):
            entries = [e.attrib.get("value") for e in item.findall("metadata")
                       if e.attrib.get("key") == "extruder"]
            if len(entries) != 1 or not entries[0].isdecimal() or int(entries[0]) < 1:
                raise WorkerError("Multi-filament 3MF object lacks an extruder.")
            tools.add(int(entries[0]) - 1)
        if "3D/3dmodel.model" in archive.namelist():
            model = ET.fromstring(archive.read("3D/3dmodel.model"))
            for triangle in model.iter():
                if not triangle.tag.endswith("}triangle"):
                    continue
                colour = triangle.get("paint_color")
                if colour is None:
                    continue
                if colour == "4":
                    tools.add(0)
                elif colour == "8":
                    tools.add(1)
                elif colour.endswith("C"):
                    try:
                        index = int(colour[:-1], 16) + 2
                    except ValueError:
                        raise WorkerError("Invalid native painted tool state.") from None
                    if index > 15:
                        raise WorkerError("Invalid native painted tool state.")
                    tools.add(index)
                else:
                    raise WorkerError("Invalid native painted tool state.")
    return tools


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



def verify_painted_cube_tool_regions(raw_gcode):
    """Offline acceptance for the fixed 20mm facet-painted cube at (75,110).

    Unlike global T0/T1 checks, this requires actual positive-E XY toolpaths
    *inside the printed cube* from both tools. Prime-tower/wipe-only tool
    changes cannot pass. This fixed-fixture check makes no claims about
    colour-boundary fidelity or physical print quality.
    """
    if (not isinstance(raw_gcode, bytes) or not raw_gcode
            or len(raw_gcode) > 64 * 1024 * 1024):
        raise WorkerError("Invalid native painted cube G-code.")
    try:
        lines = raw_gcode.decode("utf-8").splitlines()
    except UnicodeDecodeError:
        raise WorkerError("Painted cube G-code must be UTF-8.") from None

    active = None
    absolute_e = True
    absolute_xyz = True
    x = y = 0.0
    prior_e = {}
    hits = {0: 0, 1: 0}
    for raw in lines:
        code = raw.split(";", 1)[0].strip().upper()
        tool = TOOL.fullmatch(code)
        if tool:
            active = int(tool.group(1))
            continue
        command = code.split(None, 1)[0] if code else ""
        if command == "G90":
            absolute_xyz = True
        elif command == "G91":
            absolute_xyz = False
        elif command == "M82":
            absolute_e = True
        elif command == "M83":
            absolute_e = False
        elif command == "G92":
            if active is not None:
                reset = E_AXIS.search(code[3:])
                if reset:
                    prior_e[active] = float(reset.group(1))
            reset_x = re.search(r"(?:^|\s)X([-+]?(?:\d+(?:\.\d*)?|\.\d+))(?=\s|$)", code)
            reset_y = re.search(r"(?:^|\s)Y([-+]?(?:\d+(?:\.\d*)?|\.\d+))(?=\s|$)", code)
            if reset_x:
                x = float(reset_x.group(1))
            if reset_y:
                y = float(reset_y.group(1))
        elif MOVE.match(code):
            mx = re.search(r"(?:^|\s)X([-+]?(?:\d+(?:\.\d*)?|\.\d+))(?=\s|$)", code)
            my = re.search(r"(?:^|\s)Y([-+]?(?:\d+(?:\.\d*)?|\.\d+))(?=\s|$)", code)
            if mx:
                amount = float(mx.group(1))
                x = amount if absolute_xyz else x + amount
            if my:
                amount = float(my.group(1))
                y = amount if absolute_xyz else y + amount
            e = E_AXIS.search(code)
            if e and active is not None:
                value = float(e.group(1))
                old = prior_e.get(active, 0.0)
                if absolute_e:
                    prior_e[active] = value
                if ((value > old + 1e-6 if absolute_e else value > 1e-6)
                        and (mx or my) and 64 <= x <= 86 and 99 <= y <= 121
                        and active in hits):
                    hits[active] += 1
    if min(hits.values()) < 10:
        raise WorkerError(
            "Painted Bambu G-code lacks actual dual-tool deposition inside the model.")
    return {"base_tool_model_deposits": hits[0],
            "painted_tool_model_deposits": hits[1]}


def summarize_bambu_flush_signal(raw_gcode):
    """Bounded offline evidence of actual native Bambu positive-E toolpaths.

    Per-tool totals exclude retractions and never read printer firmware.
    No G-code is rewritten. This is exploratory output evidence, not proof
    that purge exits at the right physical location or correct colour.
    """
    if (not isinstance(raw_gcode, bytes) or not raw_gcode
            or len(raw_gcode) > 64 * 1024 * 1024):
        raise WorkerError("Invalid native Bambu flush evidence.")
    try:
        lines = raw_gcode.decode("utf-8").splitlines()
    except UnicodeDecodeError:
        raise WorkerError("Bambu flush evidence requires UTF-8 G-code.") from None
    if len(lines) > 1_500_000:
        raise WorkerError("Bambu flush evidence exceeds line limit.")
    active = None
    absolute_e = True
    absolute_xyz = True
    x = y = 0.0
    tower_min_x = tower_min_y = float("inf")
    tower_max_x = tower_max_y = float("-inf")
    tower_position_moves = 0
    e_last = {}
    totals = {0: 0.0, 1: 0.0}
    positive_moves = {0: 0, 1: 0}
    stationary = {0: 0.0, 1: 0.0}
    tower = {0: 0.0, 1: 0.0}
    support = {0: 0.0, 1: 0.0}
    support_feature_moves = 0
    tower_feature_moves = 0
    toolchanges = 0
    feature = ""
    for raw in lines:
        if raw.lstrip().startswith(";"):
            comment = raw.strip()[1:].strip()
            if comment.upper().startswith(("FEATURE:", "TYPE:")):
                feature = comment.split(":", 1)[-1].strip().lower()[:80]
            continue
        line = raw.split(";", 1)[0].strip().upper()
        chosen = TOOL.fullmatch(line)
        if chosen:
            nxt = int(chosen.group(1))
            if active in totals and nxt in totals and active != nxt:
                toolchanges += 1
            active = nxt
            continue
        command = line.split(None, 1)[0] if line else ""
        if command == "M82":
            absolute_e = True
        elif command == "M83":
            absolute_e = False
        elif command == "G90":
            absolute_xyz = True
        elif command == "G91":
            absolute_xyz = False
        elif command == "G92":
            if active in totals:
                e = E_AXIS.search(line[3:])
                if e:
                    e_last[active] = float(e.group(1))
            for axis, value in re.findall(
                    r"(?:^|\s)([XY])([-+]?(?:\d+(?:\.\d*)?|\.\d+))(?=\s|$)", line):
                if axis == "X":
                    x = float(value)
                else:
                    y = float(value)
        elif MOVE.match(line):
            mx = re.search(r"(?:^|\s)X([-+]?(?:\d+(?:\.\d*)?|\.\d+))(?=\s|$)", line)
            my = re.search(r"(?:^|\s)Y([-+]?(?:\d+(?:\.\d*)?|\.\d+))(?=\s|$)", line)
            if mx:
                amount = float(mx.group(1))
                x = amount if absolute_xyz else x + amount
            if my:
                amount = float(my.group(1))
                y = amount if absolute_xyz else y + amount
            if active not in totals:
                continue
            e = E_AXIS.search(line)
            if not e:
                continue
            val = float(e.group(1))
            prev = e_last.get(active, 0.0)
            if absolute_e:
                e_last[active] = val
            inc = (val - prev) if absolute_e else val
            if not 0 < inc < 10000:
                continue
            totals[active] += inc
            positive_moves[active] += 1
            if not XY.search(line):
                stationary[active] += inc
            if "support" in feature:
                support[active] += inc
                support_feature_moves += 1
            if "tower" in feature or "wipe" in feature:
                tower[active] += inc
                tower_feature_moves += 1
                if (mx or my) and all(math.isfinite(v) for v in (x, y)):
                    tower_min_x = min(tower_min_x, x)
                    tower_max_x = max(tower_max_x, x)
                    tower_min_y = min(tower_min_y, y)
                    tower_max_y = max(tower_max_y, y)
                    tower_position_moves += 1
    return {
        "positive_e_mm": {str(k): round(v, 3) for k, v in totals.items()},
        "positive_e_moves": {str(k): v for k, v in positive_moves.items()},
        "stationary_positive_e_mm": {str(k): round(v, 3) for k, v in stationary.items()},
        "tower_feature_positive_e_mm": {str(k): round(v, 3) for k, v in tower.items()},
        "support_feature_positive_e_mm": {
            str(k): round(v, 3) for k, v in support.items()},
        "support_feature_moves": support_feature_moves,
        "tower_feature_moves": tower_feature_moves,
        "tower_position_moves": tower_position_moves,
        "tower_deposition_bbox_mm": (
            {"min_x": round(tower_min_x, 3), "max_x": round(tower_max_x, 3),
             "min_y": round(tower_min_y, 3), "max_y": round(tower_max_y, 3)}
            if tower_position_moves else None),
        "toolchanges": toolchanges,
    }


def verify_bambu_fixture_variable_layers(raw_gcode):
    """Prove the pinned Bambu native 3MF fixed painted cube used the requested
    0.10mm (0-9mm) and 0.30mm (9-20mm) layer-height bands in actual G-code.

    BambuStudio 2.9.1 emits '; Z_HEIGHT: <physical Z>', not Orca's ';Z:'.
    Only strictly increasing native layer markers are accepted; travel Z,
    Z-hops and untrusted header settings cannot pass the audit.
    """
    if (not isinstance(raw_gcode, bytes) or not raw_gcode
            or len(raw_gcode) > 64 * 1024 * 1024):
        raise WorkerError("Invalid Bambu native layer audit G-code.")
    try:
        lines = raw_gcode.decode("utf-8").splitlines()
    except UnicodeDecodeError:
        raise WorkerError("Bambu native layer audit requires UTF-8.") from None
    if len(lines) > 1_500_000:
        raise WorkerError("Bambu native layer audit exceeds line limit.")
    layer = re.compile(r"^;\s*Z_HEIGHT:\s*([0-9]+(?:\.[0-9]+)?)\s*$", re.I)
    positions = []
    for raw in lines:
        match = layer.fullmatch(raw.strip())
        if match:
            z = float(match.group(1))
            if math.isfinite(z) and 0 < z <= 1000 and (
                    not positions or z > positions[-1] + 1e-5):
                positions.append(z)
    if len(positions) < 10:
        raise WorkerError("Bambu G-code lacks native layer-height markers.")
    checks = []
    for label, start, stop, wanted in (
            ("lower", 0.0, 9.0, 0.10),
            ("upper", 9.0, 20.0, 0.30)):
        values = [round(z1 - z0, 4)
                  for z0, z1 in zip(positions, positions[1:])
                  if z0 >= start + wanted and z1 <= stop - wanted]
        matched = [v for v in values if abs(v - wanted) <= max(0.018, wanted * .12)]
        if len(values) < 5 or len(matched) < max(3, math.ceil(.6 * len(values))):
            raise WorkerError("Bambu native variable layer height did not match the requested bands.")
        checks.append({"band": label, "target_height_mm": wanted,
                       "matched_layers": len(matched), "checked_layers": len(values)})
    return {"native_z_markers": len(positions), "verified_layer_bands": checks}


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
