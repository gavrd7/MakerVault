"""Engine-native bed-type selection; never substitute a cold plate for unknown.

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
# Exact OrcaSlicer 2.5.0 BedType enum from PrintConfig.hpp. Zero is
# btDefault, not a real surface; never mistake it for a cold plate.
ORCA_BED_ENUM = {
    "1": "cool", "2": "engineering", "3": "high_temp",
    "4": "textured_pei", "5": "textured_cool", "6": "supertack",
}


def native_plate_key(value):
    if type(value) is int:
        value = str(value)
    if not isinstance(value, str):
        return None
    key = value.strip().casefold()
    return NATIVE_TO_KEY.get(key) or ORCA_BED_ENUM.get(key)


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
        # Official machine presets must not silently inherit a stale process
        # bed type when their machine-model lookup failed. Locally imported
        # custom presets can explicitly declare a process bed type.
        if str(getattr(printer_profile, "provenance", "")).startswith(
                "OrcaSlicer/OrcaSlicer@"):
            raise ValueError(
                "The imported printer's default build plate could not be identified. "
                "Select a known plate explicitly instead of using the process fallback."
            )
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


def inspect_engine_plates(profile):
    """Return native plate choices for a specific engine/printer preset.

    Creality 7.3.x uses the same named bed-temperature families as its
    native project JSON. Unknown capabilities are advisory, never physical
    compatibility promises: execution validates the exact filament vector.
    """
    engine = getattr(profile, "engine", None)
    if engine == "orcaslicer":
        return inspect_native_plates(profile)
    if engine != "crealityprint":
        return {"default": None, "supported": [], "default_source": "not declared"}
    native = json.loads(resolved_native_profile(profile))
    if not isinstance(native, dict):
        raise SlicerProfileError("Native Creality printer profile is not an object.")
    default = native_plate_key(native.get("default_bed_type"))
    # Creality presets may omit Orca's support_multi_bed_types marker.
    # Expose selectable native temperatures, but never claim the machine
    # physically supports a surface that its profile explicitly excludes.
    multi = native.get("support_multi_bed_types")
    if isinstance(multi, list):
        multi = multi[0] if multi else None
    supported = list(PLATES) if str(multi).lower() not in ("0", "false") else []
    excluded = native.get("not_support_bed_types") or []
    if isinstance(excluded, str):
        excluded = re.split(r"[;,]", excluded)
    if isinstance(excluded, list):
        denied = {native_plate_key(value) or str(value).strip().lower()
                  for value in excluded}
        supported = [key for key in supported if key not in denied]
    if default and default not in supported:
        raise SlicerProfileError("Creality default plate conflicts with its supported bed types.")
    return {"default": default, "supported": supported,
            "default_source": "native Creality printer" if default else "not declared"}


def effective_creality_plate(plate_type, process, printer_profile=None):
    """Resolve a Creality 7.3.x plate without assuming any fallback heater."""
    if plate_type not in ("default", *PLATES):
        raise ValueError("Unsupported native Creality build plate.")
    if printer_profile is not None:
        allowed = inspect_engine_plates(printer_profile)
        if plate_type != "default" and plate_type not in allowed["supported"]:
            raise ValueError("Selected build plate is excluded by the Creality printer profile.")
        if plate_type == "default" and allowed["default"]:
            return allowed["default"]
    if plate_type != "default":
        return plate_type
    return native_plate_key(process.get("curr_bed_type"))


def apply_creality_plate(process_bytes, filament_bytes, plate_type, printer_profile=None):
    """Apply a native bed selection to worker-bound copies, not stored presets."""
    try:
        process = json.loads(process_bytes)
        filament = json.loads(filament_bytes)
    except (ValueError, UnicodeDecodeError, TypeError) as exc:
        raise ValueError("Invalid Creality process or filament preset.") from exc
    if not isinstance(process, dict) or not isinstance(filament, dict):
        raise ValueError("Creality native presets must be objects.")
    effective = effective_creality_plate(plate_type, process, printer_profile)
    if plate_type != "default" or effective:
        if not effective:
            raise ValueError("Creality build plate type could not be resolved.")
        validate_plate_temperature(filament, effective)
        process["curr_bed_type"] = PLATES[effective][0]
    # Preserve the engine's original default when the native profiles have
    # no resolvable selection; never guess a surface or overwrite temperatures.
    return (json.dumps(process, ensure_ascii=False, separators=(",", ":")).encode(),
            json.dumps(filament, ensure_ascii=False, separators=(",", ":")).encode())
