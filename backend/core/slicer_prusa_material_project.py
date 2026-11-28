"""Typed Prusa 2.9.7 per-object material assignments for native research.

Prusa's 3MF importer reads the per-object "extruder" option from
Metadata/Slic3r_PE_model.config. Native tools are one-based in project
metadata (1 -> T0), whereas G-code tools are zero-based.

This only prepares research fixtures. The production isolated worker still
denies Prusa multi-material inputs until separate authenticated palette,
purge and printer topology acceptance.
"""
import io
import zipfile
from defusedxml import ElementTree as SafeET
from xml.etree import ElementTree as ET

from .slicer_prusa_machine_topology import validate_prusa_model_tool_order
from .slicer_profiles import SlicerProfileError

MODEL_PART = "Metadata/Slic3r_PE_model.config"
FIXED_PARTS = frozenset({
    "3D/3dmodel.model", MODEL_PART, "[Content_Types].xml", "_rels/.rels"
})
LAYER_PART = "Metadata/Prusa_Slicer_layer_config_ranges.xml"


def add_prusa_native_model_tools(project, printer_ini, tool_indices):
    """Return an internal native project with one exact tool for each object.

    No arbitrary original project, uploaded 3MF, mesh rewrite, native printer
    macro modification, slicer process config mutation or external relationship.
    """
    try:
        if not isinstance(project, bytes) or not 0 < len(project) <= 32 * 1024 * 1024:
            raise ValueError("Invalid internally generated Prusa project.")
        topology = validate_prusa_model_tool_order(printer_ini, tool_indices)
        with zipfile.ZipFile(io.BytesIO(project)) as archive:
            names = archive.namelist()
            allowed = FIXED_PARTS | {LAYER_PART}
            if (len(set(names)) != len(names) or
                    not FIXED_PARTS.issubset(names) or
                    set(names) - allowed or
                    any(archive.getinfo(name).file_size > 96 * 1024 * 1024
                        for name in names)):
                raise ValueError("Unexpected native Prusa source project members.")
            original = archive.read(MODEL_PART)
            if b"<!" in original or b"\x00" in original:
                raise ValueError("Untrusted Prusa 3MF metadata.")
            root = SafeET.fromstring(original)
            if root.tag != "config" or root.attrib:
                raise ValueError("Invalid Prusa model configuration.")
            models = list(root)
            if len(models) != len(tool_indices):
                raise ValueError("Per-object material assignment length mismatch.")
            for index, (model, tool) in enumerate(zip(models, tool_indices), 1):
                if (model.tag != "object" or
                        model.attrib != {"id": str(index), "instances_count": "1"}):
                    raise ValueError("Unexpected Prusa object identity.")
                for meta in model:
                    if meta.tag == "metadata" and meta.get("key") == "extruder":
                        raise ValueError("Native Prusa object has an existing tool selection.")
                ET.SubElement(model, "metadata", {
                    "type": "object", "key": "extruder", "value": str(tool),
                })
            adjusted = ET.tostring(root, encoding="utf-8", xml_declaration=True)
            destination = io.BytesIO()
            with zipfile.ZipFile(destination, "w",
                                 compression=zipfile.ZIP_DEFLATED, allowZip64=False) as result:
                for name in names:
                    result.writestr(name, adjusted if name == MODEL_PART else
                                    archive.read(name))
            output = destination.getvalue()
            if len(output) > 32 * 1024 * 1024:
                raise ValueError("Native Prusa material project exceeds size cap.")
            return {"project": output, "topology": topology}
    except (OSError, TypeError, ValueError, zipfile.BadZipFile,
            ET.ParseError) as exc:
        raise SlicerProfileError("Prusa multi-tool project failed strict preparation.") from exc
