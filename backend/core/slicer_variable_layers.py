"""Validate universal layer height bands and translate exact Orca Z ranges.

3MF range translation is engine-native input, not physical printer approval.
"""
import math
import re


def validate_variable_layer_profile(value):
    if not isinstance(value, dict) or set(value) != {"version", "bands"} or (
        type(value.get("version")) is not int or value["version"] != 1
    ):
        raise ValueError("Invalid variable layer profile.")
    bands = value["bands"]
    if not isinstance(bands, list) or len(bands)>80:
        raise ValueError("Too many variable layer ranges.")
    result = []
    for band in bands:
        if not isinstance(band, dict) or set(band)!={"from_mm", "to_mm", "layer_mm"}:
            raise ValueError("Invalid variable layer band.")
        if any(type(band[k]) not in (int,float) or not math.isfinite(band[k])
               for k in ("from_mm","to_mm","layer_mm")):
            raise ValueError("Invalid layer dimensions.")
        start,end,thickness = (band[k] for k in ("from_mm","to_mm","layer_mm"))
        if not 0<=start<end<=1000 or not .05<=thickness<=.5:
            raise ValueError("Variable layer band outside supported range.")
        result.append({"from_mm":round(float(start),3),
                       "to_mm":round(float(end),3),
                       "layer_mm":round(float(thickness),3)})
    result.sort(key=lambda row:row["from_mm"])
    if any(b["from_mm"] < a["to_mm"] for a,b in zip(result,result[1:])):
        raise ValueError("Variable layer ranges overlap.")
    return {"version":1,"bands":result}


def orca_layer_config_ranges(objects_with_stl):
    """Encode exact per-object bands in Orca 2.5's native 3MF range XML.

    Unlike its smoothed variable layer-height *profile*, layer_config_ranges
    maps each interval directly to the native `layer_height` process setting.
    The IDs follow 3MF resource order, including objects without a band.
    Native part transformations are intentionally restricted here until a
    rotated/scaled per-object real-binary fixture has been verified.
    """
    from xml.etree import ElementTree as ET

    root = ET.Element("objects")
    count = 0
    for index, (item, _raw) in enumerate(objects_with_stl, start=1):
        value = item.get("variable_layer_profile")
        if not isinstance(value, dict) or not value.get("bands"):
            continue
        profile = validate_variable_layer_profile(value)
        if any(abs(float(deg)) > 0.000001 for deg in
               item.get("rotation_xyz_deg", [0, 0])) or (
               abs(float(item.get("z_mm", 0))) > 0.000001):
            raise ValueError(
                "Variable layer ranges on tilted or elevated objects need native "
                "geometry alignment verification before slicing.")
        scales = item.get("scale_xyz_percent", [item.get("scale_percent", 100)] * 3)
        if any(abs(float(scale) - 100) > 0.000001 for scale in scales):
            raise ValueError(
                "Variable layer ranges on scaled objects need native Z alignment "
                "verification before slicing.")
        node = ET.SubElement(root, "object", {"id": str(index)})
        for band in profile["bands"]:
            range_node = ET.SubElement(node, "range", {
                "min_z": format(band["from_mm"], ".3f"),
                "max_z": format(band["to_mm"], ".3f"),
            })
            option = ET.SubElement(range_node, "option", {"opt_key": "layer_height"})
            option.text = format(band["layer_mm"], ".3f")
            count += 1
    if not count:
        return None
    return ET.tostring(root, encoding="utf-8", xml_declaration=True)


_LAYER_Z = re.compile(r"^;Z:\s*([0-9]+(?:\.[0-9]+)?)\s*$", re.I)


def audit_orca_variable_layers(gcode, bands):
    """Require actual Orca layer Z increments near each requested range.

    This is observational evidence, not a printer-safety certification.
    Match the slicer's ;LAYER_CHANGE / ;Z comments, never arbitrary travel
    moves or Z-hop commands. A band too narrow to yield a measurable layer
    remains unverified rather than receiving invented success.
    """
    if not isinstance(gcode, str) or len(gcode) > 90 * 1024 * 1024:
        raise ValueError("Invalid native layer audit G-code.")
    profile = validate_variable_layer_profile({"version": 1, "bands": bands})
    positions = []
    following = 0
    for index, raw in enumerate(gcode.splitlines()):
        if index >= 2_000_000:
            raise ValueError("Native layer audit exceeds the line limit.")
        line = raw.strip()
        if line == ";LAYER_CHANGE":
            following = 8
            continue
        if following <= 0:
            continue
        following -= 1
        match = _LAYER_Z.fullmatch(line)
        if match:
            z = float(match.group(1))
            if math.isfinite(z) and (not positions or z > positions[-1] + 0.00001):
                positions.append(z)
            following = 0
    if len(positions) < 3:
        raise ValueError("G-code has insufficient native layer-height markers.")
    checks = []
    for band in profile["bands"]:
        begin, end, wanted = band["from_mm"], band["to_mm"], band["layer_mm"]
        # Prefer a full interval away from transition boundaries.
        central = [(lower, upper) for lower, upper in zip(positions, positions[1:])
                   if lower >= begin + wanted and upper <= end - wanted]
        samples = central or [(lower, upper) for lower, upper in zip(positions, positions[1:])
                              if lower >= begin - 0.0001 and upper <= end + 0.0001]
        observed = [round(upper-lower, 4) for lower, upper in samples]
        tolerance = max(.018, wanted * .12)
        matched = [delta for delta in observed if abs(delta - wanted) <= tolerance]
        if not matched:
            raise ValueError(
                "Native Orca G-code did not demonstrate the requested variable "
                "layer height in the %.3f-%.3f mm range." % (begin, end))
        checks.append({"from_mm": begin, "to_mm": end,
                       "target_layer_mm": wanted, "observed_layer_mm": matched[0]})
    return {"verified_bands": checks, "layer_markers": len(positions)}
