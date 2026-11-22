"""Add only bounded Bambu project vectors to a MakerVault-authored native 3MF.

Bambu 02.09.01.70 assumes a project holds one native filament entry per
logical tool during 3MF export. A bare core 3MF can abort in upstream CLI.
Only server-resolved owner-scoped JSON and explicit model/paint swatches feed
these vectors. No scripts, printer credentials or external file references.
"""
import io
import json
import re
import zipfile

from .slicer_profiles import SlicerProfileError

MAX_SIZE = 32 * 1024 * 1024
_HEX = re.compile(r"^#[0-9A-Fa-f]{6}$")
_MEMBERS = frozenset({
    "3D/3dmodel.model", "Metadata/model_settings.config",
    "Metadata/layer_config_ranges.xml", "[Content_Types].xml", "_rels/.rels",
})
_BAMBU = "Metadata/project_settings.config"


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
    if (not isinstance(project, bytes) or not 0 < len(project) <= MAX_SIZE
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
    vectors = {
        "printer_settings_id": _field(machine, "name", label="printer"),
        "print_settings_id": _field(print_preset, "name", label="process"),
        "filament_settings_id": material_ids,
        "filament_colour": [value.upper() for value in tool_colours],
        "filament_type": types,
        "filament_diameter": diameters,
        "nozzle_diameter": [diameter],
        "printable_height": height,
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
                        if item.file_size > MAX_SIZE:
                            raise SlicerProfileError("Unsafe source native 3MF member.")
                        target.writestr(item.filename, original.read(item.filename))
                    target.writestr(_BAMBU, json.dumps(
                        vectors, ensure_ascii=False, separators=(",", ":")))
                result = output.getvalue()
    except (zipfile.BadZipFile, OSError, ValueError) as exc:
        raise SlicerProfileError("Cannot assemble the Bambu native project settings.") from exc
    if len(result) > MAX_SIZE:
        raise SlicerProfileError("Bambu native project exceeds its size limit.")
    return result


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
