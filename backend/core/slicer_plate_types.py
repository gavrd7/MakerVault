"""Native Orca bed-type selection; never substitute a cold plate for unknown.

Printer machine-model metadata defines the default and enabled plate types.
Filament presets supply separate temperature vectors for the chosen plate.
No physical plate detection, and no inference from ambient/nozzle material.
"""
import json
import re

from .slicer_profiles import SlicerProfileError
from .slicer_native_resolution import resolved_native_profile
from .slicer_bed_artwork import (
    SOURCES, _VERSION, _official_machine_model,
)

PLATES = {
    "cool": ("Cool Plate", "cool_plate_temp"),
    "engineering": ("Engineering Plate", "eng_plate_temp"),
    "high_temp": ("High Temp Plate", "hot_plate_temp"),
    "textured_pei": ("Textured PEI Plate", "textured_plate_temp"),
    "textured_cool": ("Textured Cool Plate", "textured_cool_plate_temp"),
    "supertack": ("Supertack Plate", "supertack_plate_temp"),
}
NATIVE_TO_KEY = {native.casefold(): code for code, (native, _) in PLATES.items()}


def native_plate_key(value):
    if not isinstance(value, str):
        return None
    return NATIVE_TO_KEY.get(value.strip().casefold())


def _default_from_model(profile, native):
    # A custom local machine can explicitly declare the bed type itself.
    value = native_plate_key(native.get("default_bed_type"))
    if value:
        return value
    if profile is None or profile.engine != "orcaslicer":
        return None
    source = SOURCES["orcaslicer"][0]
    match = _VERSION.fullmatch(str(profile.engine_version or ""))
    if not match:
        return None
    ref = "v" + match.group(1)
    origin = re.fullmatch(
        re.escape(source) + "@" + re.escape(ref) +
        r"/([A-Za-z0-9_-]+)/machine/([A-Za-z0-9_. -]+\.json)",
        str(profile.provenance or ""),
    )
    if not origin or origin.group(1) not in SOURCES["orcaslicer"][1]:
        return None
    model = native.get("printer_model")
    if not isinstance(model, str) or not 0 < len(model) <= 200:
        return None
    entry = _official_machine_model(source, ref, origin.group(1), model)
    return native_plate_key(entry.get("default_bed_type")) if entry else None


def inspect_native_plates(profile):
    """UI advisory from verified owned printer data, not temperature guessing."""
    native = json.loads(resolved_native_profile(profile))
    if not isinstance(native, dict):
        raise SlicerProfileError("Native printer profile is not an object.")
    multi = native.get("support_multi_bed_types")
    if isinstance(multi, list):
        multi = multi[0] if multi else None
    # Only a positive explicit native capability enables the multi-bed
    # catalogue. Missing flags must not imply every possible plate fits.
    supported = list(PLATES) if str(multi).lower() in ("1", "true") else []
    unsupported = native.get("not_support_bed_types")
    if isinstance(unsupported, str):
        unsupported = re.split(r"[;,]", unsupported)
    if isinstance(unsupported, list):
        excluded = {native_plate_key(value) or str(value).strip().lower()
                    for value in unsupported}
        supported = [key for key in supported if key not in excluded]
    default = _default_from_model(profile, native)
    if not supported and default:
        supported = [default]
    if default and default not in supported:
        # A native profile must not claim its own default is unsupported.
        raise SlicerProfileError("Native printer default plate conflicts with supported bed types.")
    return {"default": default, "supported": supported,
            "default_source": "native printer model" if default else "not declared"}


def effective_orca_plate(plate_type, process, printer_profile=None):
    """Resolve the effective physical-plate category, never 'default' cold."""
    if plate_type not in ("default", *PLATES):
        raise ValueError("Unsupported native Orca build plate.")
    if plate_type != "default":
        if printer_profile is not None:
            supported = inspect_native_plates(printer_profile)["supported"]
            if supported and plate_type not in supported:
                raise ValueError("Selected build plate is not supported by the imported printer profile.")
        return plate_type
    # 'Native / profile default' refers to the printer's declared machine
    # plate, not a process preset's potentially stale curr_bed_type.
    if printer_profile is not None:
        metadata = inspect_native_plates(printer_profile)
        if metadata["default"]:
            return metadata["default"]
    current = native_plate_key(process.get("curr_bed_type"))
    if current:
        return current
    raise ValueError(
        "The native printer default build plate is unknown. Select an explicit "
        "build plate before slicing; no cool-plate fallback will be used."
    )


def validate_plate_temperature(filament, plate_key):
    """Do not pretend another plate's heater settings are equivalent."""
    field = PLATES[plate_key][1]
    initial = field + "_initial_layer"
    # Filament profile inheritance has already been resolved by caller.
    def read(name):
        value = filament.get(name)
        if isinstance(value, list):
            value = value[0] if value else None
        try:
            result = float(value)
        except (TypeError, ValueError):
            return None
        return result if 0 <= result <= 150 else None
    first = read(initial)
    normal = read(field)
    if first is None and normal is None:
        raise ValueError(
            "Selected filament profile does not declare a temperature for " +
            PLATES[plate_key][0] + ". Choose a compatible plate/profile."
        )
    return {"first_layer_c": first if first is not None else normal,
            "other_layers_c": normal if normal is not None else first}
