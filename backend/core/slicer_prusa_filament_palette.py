"""Prusa-only offline material palette compiler.

Each logical tool must have an explicitly resolved owner-owned filament
preset. Only reviewed scalar numeric vector options may differ; all other
settings must agree. This deliberately does not admit production MMU jobs.
"""
from decimal import Decimal, InvalidOperation
import re

from .slicer_prusa_machine_topology import prusa_machine_topology
from .slicer_prusa_native_resolution import parse_prusa_profile, resolved_prusa_profile
from .slicer_profiles import SlicerProfileError

# Native ConfigOption vector keys; expand only with genuine CLI evidence.
LIMITS = {
    "temperature": (0, 350),
    "first_layer_temperature": (0, 350),
}
NUMBER = re.compile(r"[0-9]{1,3}")


def compile_prusa_filament_palette(printer_ini, filament_inis):
    topology = prusa_machine_topology(printer_ini)
    if topology["requires_new_toolchanger_qualification"]:
        raise SlicerProfileError("Prusa six-to-eight-tool palettes require separate qualification.")
    count = topology["logical_tool_count"]
    if count < 2 or not isinstance(filament_inis, (list, tuple)) or len(filament_inis) != count:
        raise SlicerProfileError("Prusa palette requires one explicit preset per native tool.")
    presets = [parse_prusa_profile(raw, "filament") for raw in filament_inis]
    keys = set(presets[0])
    if not LIMITS.keys() <= keys or any(set(p) != keys for p in presets):
        raise SlicerProfileError("Prusa filament palette settings are incomplete or inconsistent.")
    result = {}
    for key in sorted(keys):
        values = [p[key] for p in presets]
        if key in LIMITS:
            lo, hi = LIMITS[key]
            if any(not NUMBER.fullmatch(v) or not lo <= int(v) <= hi for v in values):
                raise SlicerProfileError("Prusa filament temperature vector is invalid.")
            result[key] = ",".join(values)
        else:
            if len(set(values)) != 1:
                raise SlicerProfileError("Prusa filament palette has an unqualified differing setting.")
            result[key] = values[0]
    try:
        diameter = Decimal(result["filament_diameter"])
        if not diameter.is_finite() or not Decimal("1") <= diameter <= Decimal("3"):
            raise InvalidOperation
    except InvalidOperation:
        raise SlicerProfileError("Prusa palette filament diameter is invalid.") from None
    output = "".join(f"{key} = {value}\n" for key, value in result.items()).encode("utf-8")
    parse_prusa_profile(output, "filament")
    return output


def resolve_owned_prusa_filament_palette(printer_profile, filament_profiles, *, owner_id):
    if owner_id is None or printer_profile.owner_id != owner_id or printer_profile.kind != "printer" or
            printer_profile.engine != "prusaslicer":
        raise SlicerProfileError("Prusa palette printer profile is not owned.")
    if not isinstance(filament_profiles, (tuple, list)) or any(
        p.owner_id != owner_id or p.kind != "filament" or
        p.engine != "prusaslicer" for p in filament_profiles
    ):
        raise SlicerProfileError("Prusa palette filament profile is not owned.")
    return compile_prusa_filament_palette(
        resolved_prusa_profile(printer_profile),
        [resolved_prusa_profile(p) for p in filament_profiles],
    )
