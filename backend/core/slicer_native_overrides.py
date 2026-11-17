"""Per-job native Orca settings. Never rewrite the stored source presets.

Plate selection is an Orca project setting, separate from the filament's
temperature vectors. A colour in a visual plate becomes a native single-tool
colour only when all models use the same explicitly selected hex colour.
This is not multi-material painting or a CFS/AMS tool-to-slot assignment.
"""
import json
import re

from .slicer_plate_types import effective_orca_plate, validate_plate_temperature


ORCA_PLATES = {
    "default": None,
    "cool": "Cool Plate",
    "engineering": "Engineering Plate",
    "high_temp": "High Temp Plate",
    "textured_pei": "Textured PEI Plate",
    "textured_cool": "Textured Cool Plate",
    "supertack": "Supertack Plate",
}
_HEX = re.compile(r"^#[0-9A-Fa-f]{6}$")


def apply_orca_job_overrides(process_bytes, filament_bytes, plate_type, plate_objects, printer_profile=None):
    """Return (process, filament) bytes with bounded job-specific native overrides.

    The worker still validates both native JSON documents. The selected bed
    influences Orca's bed-temperature lookup for this filament, not any
    physical printer state.
    """
    if plate_type not in ORCA_PLATES:
        raise ValueError("Unsupported Orca build plate type.")
    try:
        process = json.loads(process_bytes)
        filament = json.loads(filament_bytes)
    except (UnicodeDecodeError, ValueError, TypeError) as exc:
        raise ValueError("Invalid native process or filament profile.") from exc
    if not isinstance(process, dict) or not isinstance(filament, dict):
        raise ValueError("Native process and filament profiles must be objects.")

    effective = effective_orca_plate(plate_type, process, printer_profile)
    process["curr_bed_type"] = ORCA_PLATES[effective]
    # The bed heater vector is a filament-native setting. Fail explicitly
    # rather than borrow a cold/smooth plate's value for a textured sheet.
    validate_plate_temperature(filament, effective)
    if plate_objects:
        colours = {item.get("color", "").upper() for item in plate_objects
                   if isinstance(item, dict)}
        if len(colours) == 1:
            colour = next(iter(colours))
            if _HEX.fullmatch(colour):
                filament["default_filament_colour"] = [colour]
                process["filament_colour"] = [colour]
    result_process = json.dumps(process, ensure_ascii=False, separators=(",", ":")).encode()
    result_filament = json.dumps(filament, ensure_ascii=False, separators=(",", ":")).encode()
    if max(len(result_process), len(result_filament)) > 1024 * 1024:
        raise ValueError("Slicing settings exceed the supported native profile size.")
    return result_process, result_filament
