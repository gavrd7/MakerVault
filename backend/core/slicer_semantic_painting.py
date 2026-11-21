"""Strict draft-only semantic surface annotations.

Seam enforcers/blockers and fuzzy skin masks have independent meaning.
These are never substituted for native G-code settings or colour slots.
"""
from .slicer_colour_painting import validate_colour_paint

_PALETTES = {
    "seam": [
        {"color": "#e58a58", "label": "Enforce seam"},
        {"color": "#537ccf", "label": "Block seam"},
    ],
    "fuzzy": [{"color": "#c69cde", "label": "Paint fuzzy skin"}],
}


def validate_semantic_paint(value, kind):
    if kind not in _PALETTES or not isinstance(value, dict) or set(value) != {
        "version", "signature", "regions"
    } or type(value.get("version")) is not int or value["version"] != 2:
        raise ValueError("Invalid semantic painting metadata.")
    checked = validate_colour_paint({**value, "palette": _PALETTES[kind]})
    return {key: checked[key] for key in ("version", "signature", "regions")}
