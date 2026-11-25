"""Prusa MMU/XL explicit-tool 3MF construction; offline candidate only.

Native PrusaSlicer 2.9.7 real G-code separately demonstrated per-object
extruder metadata: tool 1 -> T0, tool 2 -> T1. The normal authenticated
single-material worker deliberately rejects this dialect until the exact
filament palette, owner binding, purge and printer-submission guard pass their
own independent acceptance. Do not call from production job execution.
"""
import io
import zipfile
from defusedxml import ElementTree as SafeET
from xml.etree import ElementTree as ET

from .slicer_prusa_3mf import build_prusa_native_3mf
from .slicer_prusa_machine_topology import validate_prusa_model_tool_order
from .slicer_profiles import SlicerProfileError


def build_prusa_multitool_candidate(rows, *, printer_ini, tools,
                                     bed_width, bed_depth):
    try:
        topology = validate_prusa_model_tool_order(printer_ini, tools)
    except ValueError as exc:
        raise SlicerProfileError(str(exc)) from exc
    if len(rows) != len(tools):
        raise SlicerProfileError("Native Prusa tool count does not match printable objects.")
    for item, _source in rows:
        if not isinstance(item, dict) or any(
            item.get(key) for key in (
                "modifier_volumes", "process_overrides", "colour_paint",
                "support_paint", "seam_paint", "fuzzy_skin_paint",
                "variable_layer_profile", "negative_volumes", "material_slot",
            )
        ):
            raise SlicerProfileError("Prusa multi-tool candidate cannot discard advanced edits.")
    base = build_prusa_native_3mf(rows, bed_width=bed_width, bed_depth=bed_depth)
    out = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(base)) as src, zipfile.ZipFile(
            out, "w", compression=zipfile.ZIP_DEFLATED,
            allowZip64=False) as dest:
        for name in src.namelist():
            part = src.read(name)
            if name == "Metadata/Slic3r_PE_model.config":
                root = SafeET.fromstring(part)
                objects = root.findall("./object")
                if len(objects) != len(tools):
                    raise SlicerProfileError("Prusa tool candidate object count mismatch.")
                for item, tool in zip(objects, tools):
                    ET.SubElement(item, "metadata", {
                        "type": "object", "key": "extruder", "value": str(tool)})
                part = ET.tostring(root, encoding="utf-8", xml_declaration=True)
            dest.writestr(name, part)
    result = out.getvalue()
    if len(result) > 32 * 1024 * 1024:
        raise SlicerProfileError("Native Prusa multi-tool project exceeds its size limit.")
    return result, topology
