"""Add only bounded Bambu project vectors to a MakerVault-authored native 3MF.

Bambu 02.09.01.70 assumes a project holds one native filament entry per
logical tool during 3MF export. A bare core 3MF can abort in upstream CLI.
Only server-resolved owner-scoped JSON and explicit model/paint swatches feed
these vectors. No scripts, printer credentials or external file references.
"""
import io
import json
import math
import re
import zipfile
from xml.etree import ElementTree as ET
from defusedxml.ElementTree import fromstring as safe_xml_fromstring
from defusedxml.common import DefusedXmlException

from .slicer_resource_budget import project_archive_budget, xml_geometry_budget
from .slicer_profiles import SlicerProfileError


_HEX = re.compile(r"^#[0-9A-Fa-f]{6}$")
_MEMBERS = frozenset({
    "3D/3dmodel.model", "Metadata/model_settings.config",
    "Metadata/layer_config_ranges.xml", "[Content_Types].xml", "_rels/.rels",
})
_BAMBU = "Metadata/project_settings.config"
_CORE = "http://schemas.microsoft.com/3dmanufacturing/core/2015/02"
_VARIANT_FLOATS = {
    "filament_flow_ratio": (0.5, 1.5),
    "nozzle_temperature": (100, 400),
    "nozzle_temperature_initial_layer": (100, 400),
    "filament_max_volumetric_speed": (0.1, 100),
    "filament_retraction_length": (0, 30),
}


def _variant_values(document, count, key, low, high):
    values = document.get(key)
    if not isinstance(values, list) or len(values) != count:
        raise SlicerProfileError("Bambu native material option " + key + " is incomplete.")
    result = []
    for value in values:
        if key == "filament_retraction_length" and value == "nil":
            result.append(value)
            continue
        if (not isinstance(value, str) or
                not re.fullmatch(r"(?:[0-9]{1,3})(?:\.[0-9]{1,4})?", value)):
            raise SlicerProfileError("Invalid Bambu native material option " + key + ".")
        if not low <= float(value) <= high:
            raise SlicerProfileError("Unsafe Bambu native material option " + key + ".")
        result.append(value)
    return result


def _mark_bambu_native_model(raw):
    try:
        root = safe_xml_fromstring(raw)
    except (ET.ParseError, DefusedXmlException) as exc:
        raise SlicerProfileError("Malformed native Bambu model XML.") from exc
    if root.tag != "{" + _CORE + "}model":
        raise SlicerProfileError("Invalid Bambu model namespace.")
    existing = [(node.get("name"), node.text)
                for node in root if node.tag == "{" + _CORE + "}metadata"
                and node.get("name") in ("Application", "BambuStudio:3mfVersion")]
    if existing == [("Application", "BambuStudio-02.09.01.70"),
                    ("BambuStudio:3mfVersion", "1")]:
        return raw
    for node in list(root):
        if node.tag == "{" + _CORE + "}metadata" and node.get("name") in (
                "Application", "BambuStudio:3mfVersion"):
            root.remove(node)
    for index, (name, value) in enumerate((
            ("Application", "BambuStudio-02.09.01.70"),
            ("BambuStudio:3mfVersion", "1"))):
        node = ET.Element("{" + _CORE + "}metadata", {"name": name})
        node.text = value
        root.insert(index, node)
    ET.register_namespace("", _CORE)
    return ET.tostring(root, encoding="utf-8")



def _native(raw, label):
    if not isinstance(raw, bytes) or not 0 < len(raw) < 1024 * 1024:
        raise SlicerProfileError("Invalid " + label + " profile bytes.")
    try:
        result = json.loads(raw)
    except (ValueError, UnicodeDecodeError):
        raise SlicerProfileError("Invalid " + label + " native JSON.") from None
    if not isinstance(result, dict):
        raise SlicerProfileError("Invalid native " + label + " preset.")
    return result


def _field(document, key, *, label):
    value = document.get(key)
    if isinstance(value, list):
        value = value[0] if len(value) == 1 else None
    if not isinstance(value, str) or not 1 <= len(value) <= 200:
        raise SlicerProfileError("Missing " + label + " native " + key + ".")
    return value


def add_bambu_project_settings(project, *, printer, process, filaments,
                               tool_colours):
    """Bind N exact native filaments to N 3MF logical tools (2..16)."""
    if (not isinstance(project, bytes) or not 0 < len(project) <= project_archive_budget()
            or not isinstance(filaments, (list, tuple)) or not 2 <= len(filaments) <= 16
            or not isinstance(tool_colours, (list, tuple))
            or len(tool_colours) != len(filaments)
            or any(not isinstance(c, str) or not _HEX.fullmatch(c)
                   for c in tool_colours)):
        raise SlicerProfileError("Bambu native filament assignments are incomplete.")
    machine = _native(printer, "machine")
    print_preset = _native(process, "process")
    sources = [_native(item, "filament") for item in filaments]
    diameter = _field(machine, "nozzle_diameter", label="machine")
    if not re.fullmatch(r"(?:0\.[1-9][0-9]?|[12](?:\.[0-9]{1,2})?)", diameter):
        raise SlicerProfileError("Invalid Bambu machine nozzle diameter.")
    height = _field(machine, "printable_height", label="machine")
    try:
        height_mm = float(height)
    except ValueError:
        raise SlicerProfileError("Invalid Bambu machine printable height.") from None
    if not 1 <= height_mm <= 2000 or not re.fullmatch(r"[0-9]+(?:\.[0-9]{1,3})?", height):
        raise SlicerProfileError("Invalid Bambu machine printable height.")
    material_ids = [_field(item, "name", label="filament") for item in sources]
    types = [_field(item, "filament_type", label="filament") for item in sources]
    diameters = [_field(item, "filament_diameter", label="filament") for item in sources]
    filament_ids = []
    support_flags = []
    self_indices = []
    extruder_variants = []
    material_variant_values = {key: [] for key in _VARIANT_FLOATS}
    for index, item in enumerate(sources, 1):
        native_id = _field(item, "filament_id", label="filament")
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,32}", native_id):
            raise SlicerProfileError("Unsafe Bambu native filament ID.")
        variants = item.get("filament_extruder_variant")
        if (not isinstance(variants, list) or not 1 <= len(variants) <= 4
                or any(not isinstance(v, str) or not re.fullmatch(
                    r"[A-Za-z0-9 -]{1,64}", v) for v in variants)
                or len(set(variants)) != len(variants)):
            raise SlicerProfileError("Bambu native filament variants are incomplete.")
        support = item.get("filament_is_support", ["0"])
        if isinstance(support, str):
            support = [support]
        if (not isinstance(support, list) or not 1 <= len(support) <= 4
                or any(value not in ("0", "1") for value in support)
                or len(set(support)) != 1):
            raise SlicerProfileError("Unsafe Bambu filament support classification.")
        support_flags.append(support[0])
        filament_ids.append(native_id)
        self_indices.extend([str(index)] * len(variants))
        extruder_variants.extend(variants)
        for key, (lower, upper) in _VARIANT_FLOATS.items():
            material_variant_values[key].extend(
                _variant_values(item, len(variants), key, lower, upper))
    vectors = {
        "printer_settings_id": _field(machine, "name", label="printer"),
        "print_settings_id": _field(print_preset, "name", label="process"),
        "filament_settings_id": material_ids,
        "filament_colour": [value.upper() for value in tool_colours],
        "filament_type": types,
        "filament_diameter": diameters,
        "filament_ids": filament_ids,
        "filament_is_support": support_flags,
        "filament_self_index": self_indices,
        "filament_extruder_variant": extruder_variants,
        "nozzle_diameter": [diameter],
        "printable_height": height,
        **material_variant_values,
    }
    try:
        with zipfile.ZipFile(io.BytesIO(project)) as original:
            info = original.infolist()
            names = [item.filename for item in info]
            if (not 4 <= len(info) <= 5 or len(set(names)) != len(names)
                    or set(names) - _MEMBERS or _BAMBU in names
                    or "3D/3dmodel.model" not in names
                    or "Metadata/model_settings.config" not in names):
                raise SlicerProfileError("Unsupported Bambu input project package.")
            with io.BytesIO() as output:
                with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED,
                                     allowZip64=False) as target:
                    for item in info:
                        if item.file_size > project_archive_budget():
                            raise SlicerProfileError("Unsafe source native 3MF member.")
                        value = original.read(item.filename)
                        if item.filename == "3D/3dmodel.model":
                            value = _mark_bambu_native_model(value)
                        target.writestr(item.filename, value)
                    target.writestr(_BAMBU, json.dumps(
                        vectors, ensure_ascii=False, separators=(",", ":")))
                result = output.getvalue()
    except (zipfile.BadZipFile, OSError, ValueError) as exc:
        raise SlicerProfileError("Cannot assemble the Bambu native project settings.") from exc
    if len(result) > project_archive_budget():
        raise SlicerProfileError("Bambu native project exceeds its size limit.")
    return result


def apply_bambu_prime_tower_position(process_bytes, tower, *, bed_width, bed_depth):
    """Apply the normal MakerVault tower X/Y control to a native Bambu process.

    Bambu Studio 2.9.1 uses the same wipe_tower_x/y project settings as Orca.
    This is a worker-bound profile copy, never a stored native preset.
    """
    if (not isinstance(tower, dict) or set(tower) != {"x", "y"}
            or any(type(tower[k]) not in (float, int) or
                   not math.isfinite(tower[k]) for k in ("x", "y"))
            or any(type(value) not in (float, int) or
                   not math.isfinite(value) or value <= 0
                   for value in (bed_width, bed_depth))):
        raise SlicerProfileError("Invalid Bambu prime tower position.")
    doc = _native(process_bytes, "process")
    raw_width = doc.get("prime_tower_width", "35")
    if isinstance(raw_width, list):
        raw_width = raw_width[0] if len(raw_width) == 1 else None
    try:
        width = float(raw_width)
    except (TypeError, ValueError, OverflowError):
        raise SlicerProfileError("Invalid Bambu prime tower width.") from None
    x, y = tower["x"], tower["y"]
    if (not math.isfinite(width) or not 2 <= width <= 200
            or not (0 <= x <= bed_width - width and 0 <= y < bed_depth)):
        raise SlicerProfileError("Bambu prime tower exceeds the selected plate.")
    doc["wipe_tower_x"] = [str(round(x, 3))]
    doc["wipe_tower_y"] = [str(round(y, 3))]
    return json.dumps(doc, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def selected_bambu_tool_colours(objects, bindings, count):
    """Use the same explicit model/paint swatches that were mapped to tools."""
    from .slicer_native_material_palette import native_colour_tool_maps
    # The caller supplies the authenticated current printer ID per swatch.
    result = {}
    for item in objects:
        slot = item.get("material_slot") or {}
        tool = bindings.get(slot.get("slot_id"))
        colour = item.get("color")
        if tool is None or not isinstance(colour, str) or not _HEX.fullmatch(colour):
            raise SlicerProfileError("A Bambu material lacks its selected filament colour.")
        if tool in result and result[tool] != colour.upper():
            raise SlicerProfileError("One Bambu filament tool has conflicting model colours.")
        result[tool] = colour.upper()
    if set(result) != set(range(count)):
        # Painted colours can use a different tool than the base object's.
        for item in objects:
            paint = item.get("colour_paint") or {}
            for swatch in paint.get("palette") or []:
                if not isinstance(swatch, dict):
                    continue
                tool = bindings.get(swatch.get("slot_id"))
                colour = swatch.get("color")
                if tool is None or not isinstance(colour, str) or not _HEX.fullmatch(colour):
                    continue
                if tool in result and result[tool] != colour.upper():
                    raise SlicerProfileError("Painted Bambu filament colour conflicts with its tool.")
                result[tool] = colour.upper()
    if set(result) != set(range(count)):
        raise SlicerProfileError("Every native Bambu filament tool needs a selected colour.")
    return tuple(result[index] for index in range(count))
