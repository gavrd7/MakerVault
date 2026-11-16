"""Validate support enforcer/blocker surface regions.

The stored 0/1 values are semantic actions, NEVER filament/tool identifiers.
A separate Orca 2.5 adapter translates clipped patches for offline slicing
only; these draft annotations are not yet approved for printer submission.
"""
from .slicer_colour_painting import validate_colour_paint

_PALETTE = [
    {"color": "#35b779", "label": "Enforce supports"},
    {"color": "#e56b6f", "label": "Block supports"},
]


def validate_support_paint(value):
    if not isinstance(value, dict) or set(value) != {"version", "signature", "regions"}:
        raise ValueError("Invalid support painting metadata.")
    if value["version"] != 2 or type(value["version"]) is not int:
        raise ValueError("Unsupported support painting version.")
    validated = validate_colour_paint({**value, "palette": _PALETTE})
    return {key: validated[key] for key in ("version", "signature", "regions")}
