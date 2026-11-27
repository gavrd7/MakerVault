"""Pinned PrusaSlicer 2.9.7 native layer ranges and G-code semantics.

Source: PrusaSlicer 450d70dd src/libslic3r/Format/3mf.cpp
LAYER_CONFIG_RANGES_FILE is Metadata/Prusa_Slicer_layer_config_ranges.xml,
with <objects><object id="1"><range min_z="..." max_z="...">
<option opt_key="layer_height">...</option>...
No arbitrary 3MF entries or native setting keys may be supplied by clients.
"""
import math
import re
from xml.etree import ElementTree as ET

from .slicer_variable_layers import validate_variable_layer_profile

PATH = "Metadata/Prusa_Slicer_layer_config_ranges.xml"
_LAYER_Z = re.compile(r"^;\s*Z:\s*([0-9]+(?:\.[0-9]+)?)\s*$", re.I)


def prusa_layer_config_ranges(rows):
    root = ET.Element("objects")
    count = 0
    for index, (item, _source) in enumerate(rows, 1):
        value = item.get("variable_layer_profile")
        if not isinstance(value, dict) or not value.get("bands"):
            continue
        profile = validate_variable_layer_profile(value)
        # Native ranges are object-local. The qualified first pass uses
        # geometries whose Z axis and height are unchanged by transforms.
        if any(abs(float(v)) > 1e-6 for v in
               item.get("rotation_xyz_deg", [0, 0])):
            raise ValueError("Prusa layer ranges on tilted objects require native proof.")
        if abs(float(item.get("z_mm", 0))) > 1e-6:
            raise ValueError("Prusa layer ranges on elevated objects require native proof.")
        scales = item.get("scale_xyz_percent",
                          [item.get("scale_percent", 100)] * 3)
        if any(abs(float(v) - 100) > 1e-6 for v in scales):
            raise ValueError("Prusa layer ranges on scaled objects require native proof.")
        node = ET.SubElement(root, "object", {"id": str(index)})
        for band in profile["bands"]:
            interval = ET.SubElement(node, "range", {
                "min_z": format(band["from_mm"], ".3f"),
                "max_z": format(band["to_mm"], ".3f"),
            })
            setting = ET.SubElement(interval, "option", {"opt_key": "layer_height"})
            setting.text = format(band["layer_mm"], ".3f")
            count += 1
    if count == 0:
        return None
    return ET.tostring(root, encoding="utf-8", xml_declaration=True)


def audit_prusa_variable_layers(gcode, bands):
    """Require measured Z step changes in real Prusa-generated G-code.

    Never approve solely because a 3MF XML setting exists. At least two
    in-band layers must demonstrate requested step sizes with majority match.
    """
    if not isinstance(gcode, str) or len(gcode) > 90 * 1024 * 1024:
        raise ValueError("Invalid Prusa variable layer G-code.")
    profile = validate_variable_layer_profile({"version": 1, "bands": bands})
    zs = []
    following = 0
    for index, line in enumerate(gcode.splitlines()):
        if index > 2_000_000:
            raise ValueError("Prusa variable layer audit line cap exceeded.")
        value = line.strip()
        if value == ";LAYER_CHANGE":
            following = 8
            continue
        if not following:
            continue
        following -= 1
        match = _LAYER_Z.fullmatch(value)
        if match:
            z = float(match.group(1))
            if math.isfinite(z) and 0 < z <= 1000 and (
                    not zs or z > zs[-1] + 1e-5):
                zs.append(z)
            following = 0
    if len(zs) < 3:
        raise ValueError("Prusa G-code lacks native layer Z markers.")
    results = []
    for band in profile["bands"]:
        start, end, target = band["from_mm"], band["to_mm"], band["layer_mm"]
        samples = [z1-z0 for z0,z1 in zip(zs,zs[1:])
                   if z0 >= start + target and z1 <= end - target]
        if not samples:
            samples = [z1-z0 for z0,z1 in zip(zs,zs[1:])
                       if z0 >= start - .0001 and z1 <= end + .0001]
        tolerance = max(.018, target * .12)
        matched = [v for v in samples if abs(v-target) <= tolerance]
        if len(matched) < 2 or len(matched) < math.ceil(.6*len(samples)):
            raise ValueError("Prusa G-code did not demonstrate the requested layer height.")
        results.append({"from_mm": start, "to_mm": end,
                        "target_layer_mm": target,
                        "verified_layers": len(matched)})
    return {"verified_bands": results, "layer_markers": len(zs)}
