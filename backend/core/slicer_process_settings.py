"""Bounded, process-only OrcaSlicer settings for the interactive workbench.

These are *native process keys*, not a synthetic MakerVault slicer format.
Overrides are applied only to an ephemeral resolved native process profile.
No printer/filament/start/filament-change G-code or post-processing fields
are editable through this interface. An absent key is never fabricated.
"""
import json
import math

from .slicer_profiles import SlicerProfileError, _check_orca_json

# key: (category, user-visible label, unit, minimum, maximum, integer_only)
PROCESS_FIELDS = {
    "layer_height": ("Quality", "Layer height", "mm", 0.05, 1.0, False),
    "initial_layer_print_height": ("Quality", "First layer height", "mm", 0.05, 1.0, False),
    "line_width": ("Quality", "Default line width", "mm", 0.1, 2.0, False),
    "outer_wall_line_width": ("Quality", "Outer wall line width", "mm", 0.1, 2.0, False),
    "wall_loops": ("Strength", "Wall loops", "", 1, 12, True),
    "top_shell_layers": ("Strength", "Top shell layers", "", 0, 20, True),
    "bottom_shell_layers": ("Strength", "Bottom shell layers", "", 0, 20, True),
    "sparse_infill_density": ("Strength", "Sparse infill density", "%", 0, 100, False),
    "outer_wall_speed": ("Speed", "Outer wall speed", "mm/s", 5, 500, False),
    "inner_wall_speed": ("Speed", "Inner wall speed", "mm/s", 5, 500, False),
    "sparse_infill_speed": ("Speed", "Sparse infill speed", "mm/s", 5, 500, False),
    "travel_speed": ("Speed", "Travel speed", "mm/s", 10, 1000, False),
    "support_threshold_angle": ("Supports", "Support threshold angle", "°", 0, 90, False),
    "support_interface_top_layers": ("Supports", "Top interface layers", "", 0, 10, True),
    "brim_width": ("Others", "Brim width", "mm", 0, 50, False),
    "skirt_loops": ("Others", "Skirt loops", "", 0, 20, True),
    "inner_wall_line_width": ("Quality", "Inner wall line width", "mm", 0.1, 2.0, False),
    "top_surface_line_width": ("Quality", "Top surface line width", "mm", 0.1, 2.0, False),
    "initial_layer_line_width": ("Quality", "First layer line width", "mm", 0.1, 2.0, False),
    "top_surface_speed": ("Speed", "Top surface speed", "mm/s", 5, 500, False),
    "initial_layer_speed": ("Speed", "First layer speed", "mm/s", 5, 300, False),
    "initial_layer_infill_speed": ("Speed", "First layer infill speed", "mm/s", 5, 300, False),
    "outer_wall_acceleration": ("Speed", "Outer wall acceleration", "mm/s²", 50, 30000, False),
    "inner_wall_acceleration": ("Speed", "Inner wall acceleration", "mm/s²", 50, 30000, False),
    "travel_acceleration": ("Speed", "Travel acceleration", "mm/s²", 50, 30000, False),
    "sparse_infill_line_width": ("Strength", "Sparse infill line width", "mm", 0.1, 2.0, False),
    "support_speed": ("Supports", "Support speed", "mm/s", 5, 500, False),
    "support_interface_speed": ("Supports", "Support interface speed", "mm/s", 5, 500, False),
    # Quality: exact native numeric values (no expression / mixed-unit coercion).
    "internal_solid_infill_line_width": ("Quality", "Internal solid infill line width", "mm", 0.1, 2, False),
    "support_line_width": ("Quality", "Support line width", "mm", 0.1, 2, False),
    "slice_closing_radius": ("Quality", "Slice gap closing radius", "mm", 0, 1, False),
    "resolution": ("Quality", "Resolution", "mm", 0.001, 1, False),
    "xy_hole_compensation": ("Quality", "X-Y hole compensation", "mm", -2, 2, False),
    "xy_contour_compensation": ("Quality", "X-Y contour compensation", "mm", -2, 2, False),
    "elefant_foot_compensation": ("Quality", "Elephant foot compensation", "mm", 0, 2, False),
    "elefant_foot_compensation_layers": ("Quality", "Elephant foot compensation layers", "", 1, 10, True),
    "top_surface_flow_ratio": ("Quality", "Top surface flow ratio", "", 0.5, 2, False),
    "bottom_surface_flow_ratio": ("Quality", "Bottom surface flow ratio", "", 0.5, 2, False),
    "bridge_flow": ("Quality", "Bridge flow ratio", "", 0.5, 2, False),
    "internal_bridge_flow": ("Quality", "Internal bridge flow ratio", "", 0.5, 2, False),
    "fuzzy_skin_point_distance": ("Quality", "Fuzzy skin point distance", "mm", 0.05, 5, False),
    "fuzzy_skin_thickness": ("Quality", "Fuzzy skin thickness", "mm", 0.01, 3, False),
    # Strength and infill.
    "top_shell_thickness": ("Strength", "Top shell thickness", "mm", 0, 10, False),
    "bottom_shell_thickness": ("Strength", "Bottom shell thickness", "mm", 0, 10, False),
    "sparse_infill_direction": ("Strength", "Sparse infill direction", "°", -360, 360, False),
    "solid_infill_direction": ("Strength", "Solid infill direction", "°", -360, 360, False),
    "infill_wall_overlap": ("Strength", "Infill/wall overlap", "%", 0, 100, False),
    "top_surface_density": ("Strength", "Top surface density", "%", 0, 100, False),
    "bottom_surface_density": ("Strength", "Bottom surface density", "%", 0, 100, False),
    "minimum_sparse_infill_area": ("Strength", "Minimum sparse infill threshold", "mm²", 0, 1000, False),
    # Speed and acceleration.
    "internal_solid_infill_speed": ("Speed", "Internal solid infill speed", "mm/s", 5, 500, False),
    "gap_infill_speed": ("Speed", "Gap infill speed", "mm/s", 5, 500, False),
    "default_acceleration": ("Speed", "Normal printing acceleration", "mm/s²", 50, 30000, False),
    "initial_layer_acceleration": ("Speed", "First layer acceleration", "mm/s²", 50, 30000, False),
    "top_surface_acceleration": ("Speed", "Top surface acceleration", "mm/s²", 50, 30000, False),
    # Supports: generated only from existing, resolved native profile keys.
    "support_bottom_z_distance": ("Supports", "Bottom Z distance", "mm", 0, 5, False),
    "support_top_z_distance": ("Supports", "Top Z distance", "mm", 0, 5, False),
    "support_base_pattern_spacing": ("Supports", "Base pattern spacing", "mm", 0.1, 15, False),
    "support_interface_spacing": ("Supports", "Interface pattern spacing", "mm", 0, 15, False),
    "support_bottom_interface_spacing": ("Supports", "Bottom interface spacing", "mm", 0, 15, False),
    "support_interface_bottom_layers": ("Supports", "Bottom interface layers", "", 0, 10, True),
    "raft_layers": ("Supports", "Raft layers", "", 0, 10, True),
    "support_wall_loops": ("Supports", "Support wall loops", "", 0, 10, True),
    "support_object_xy_distance": ("Supports", "Support/object XY distance", "mm", 0, 10, False),
    # Skirt / brim; G-code output templates remain intentionally unavailable.
    "skirt_distance": ("Others", "Skirt distance", "mm", 0, 50, False),
    "skirt_height": ("Others", "Skirt height", "layers", 1, 25, True),
    "skirt_speed": ("Others", "Skirt speed", "mm/s", 5, 500, False),
    "brim_object_gap": ("Others", "Brim/object gap", "mm", 0, 10, False),
    "brim_flow_ratio": ("Others", "Brim flow ratio", "", 0.5, 2, False),
}


# Only recognised, existing Orca enum values may be replaced.
CHOICE_FIELDS = {
    "sparse_infill_pattern": ("Strength", "Sparse infill pattern", (
        ("grid", "Grid"), ("gyroid", "Gyroid"), ("rectilinear", "Rectilinear"),
        ("honeycomb", "Honeycomb"), ("cubic", "Cubic"),
    )),
    "seam_position": ("Quality", "Seam position", (
        ("aligned", "Aligned"), ("nearest", "Nearest"), ("rear", "Rear"),
        ("random", "Random"),
    )),
}
TOGGLE_FIELDS = {
    "enable_support": ("Supports", "Generate supports"),
    "support_on_build_plate_only": ("Supports", "On build plate only"),
    "support_remove_small_overhang": ("Supports", "Ignore small overhangs"),
    "detect_thin_wall": ("Strength", "Detect thin walls"),
    "alternate_extra_wall": ("Strength", "Alternate extra wall"),
    "infill_combination": ("Strength", "Infill combination"),
    "spiral_mode": ("Others", "Spiral vase"),
    "ironing_support": ("Supports", "Ironing support interface"),
    "reduce_infill_retraction": ("Others", "Reduce infill retraction"),
}
ALL_FIELDS = set(PROCESS_FIELDS) | set(CHOICE_FIELDS) | set(TOGGLE_FIELDS)

# Curated from OrcaSlicer process panels. Basic contains ordinary, frequently
# adjusted print outcomes. All other supported fields appear in Advanced.
BASIC_FIELDS = frozenset({
    "layer_height", "initial_layer_print_height", "line_width",
    "wall_loops", "top_shell_layers", "bottom_shell_layers",
    "sparse_infill_density", "sparse_infill_pattern", "seam_position",
    "outer_wall_speed", "inner_wall_speed", "sparse_infill_speed",
    "travel_speed", "initial_layer_speed", "enable_support",
    "support_threshold_angle", "support_on_build_plate_only",
    "brim_width", "skirt_loops",
})
SECTIONS = {
    "Quality": {
        "Layer height": {"layer_height", "initial_layer_print_height"},
        "Line width": {"line_width", "outer_wall_line_width", "inner_wall_line_width",
                       "top_surface_line_width", "initial_layer_line_width",
                       "sparse_infill_line_width", "internal_solid_infill_line_width",
                       "support_line_width"},
        "Seam": {"seam_position"},
        "Precision": {"slice_closing_radius", "resolution", "xy_hole_compensation",
                       "xy_contour_compensation", "elefant_foot_compensation",
                       "elefant_foot_compensation_layers"},
        "Walls and surfaces": {"top_surface_flow_ratio", "bottom_surface_flow_ratio"},
        "Bridging": {"bridge_flow", "internal_bridge_flow"},
        "Fuzzy skin": {"fuzzy_skin_point_distance", "fuzzy_skin_thickness"},
    },
    "Strength": {
        "Walls": {"wall_loops", "detect_thin_wall", "alternate_extra_wall"},
        "Top/bottom shells": {"top_shell_layers", "bottom_shell_layers",
                              "top_shell_thickness", "bottom_shell_thickness",
                              "top_surface_density", "bottom_surface_density"},
        "Infill": {"sparse_infill_density", "sparse_infill_pattern",
                   "sparse_infill_direction", "solid_infill_direction",
                   "infill_wall_overlap", "infill_combination",
                   "minimum_sparse_infill_area", "sparse_infill_line_width"},
    },
    "Speed": {
        "First layer speed": {"initial_layer_speed", "initial_layer_infill_speed"},
        "Other layers speed": {"outer_wall_speed", "inner_wall_speed",
                               "sparse_infill_speed", "internal_solid_infill_speed",
                               "top_surface_speed", "gap_infill_speed"},
        "Travel speed": {"travel_speed"},
        "Acceleration": {"default_acceleration", "outer_wall_acceleration",
                         "inner_wall_acceleration", "initial_layer_acceleration",
                         "top_surface_acceleration", "travel_acceleration"},
    },
    "Supports": {
        "Support": {"enable_support", "support_threshold_angle",
                    "support_on_build_plate_only", "support_remove_small_overhang"},
        "Raft": {"raft_layers"},
        "Support ironing": {"ironing_support"},
        "Advanced": {"support_top_z_distance", "support_bottom_z_distance",
                     "support_wall_loops", "support_base_pattern_spacing",
                     "support_interface_top_layers", "support_interface_bottom_layers",
                     "support_interface_spacing", "support_bottom_interface_spacing",
                     "support_object_xy_distance", "support_speed",
                     "support_interface_speed"},
    },
    "Others": {
        "Skirt": {"skirt_loops", "skirt_distance", "skirt_height", "skirt_speed"},
        "Brim": {"brim_width", "brim_object_gap", "brim_flow_ratio"},
        "Special mode": {"spiral_mode"},
        "G-code output": {"reduce_infill_retraction"},
    },
}
SECTION_FOR = {
    key: section for group in SECTIONS.values()
    for section, keys in group.items() for key in keys
}



def _native_scalar(value):
    if isinstance(value, list):
        if not value or len(value) > 8 or any(item != value[0] for item in value):
            return None
        value = value[0]
    return value if isinstance(value, str) else None


def _scalar(value):
    if isinstance(value, list):
        if not value or len(value) > 8 or any(item != value[0] for item in value):
            return None
        value = value[0]
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        return None
    try:
        result = float(str(value).strip().removesuffix("%"))
    except ValueError:
        return None
    return result if math.isfinite(result) else None


def process_schema(raw):
    """Describe present, recognised keys in an integrity-checked process preset."""
    try:
        profile = _check_orca_json(raw.decode("utf-8-sig"))
    except (UnicodeDecodeError, ValueError):
        raise SlicerProfileError("Cannot inspect the selected native process profile.") from None
    result = {}
    for key, (category, label, unit, lo, hi, integer) in PROCESS_FIELDS.items():
        if key not in profile:
            continue
        current = _scalar(profile[key])
        if current is None or not lo <= current <= hi:
            continue
        result[key] = {
            "category": category, "label": label, "unit": unit,
            "minimum": lo, "maximum": hi, "integer": integer,
            "current": current, "level": "basic" if key in BASIC_FIELDS else "advanced",
            "section": SECTION_FOR.get(key, "Advanced"),
        }
    for key, (category, label, options) in CHOICE_FIELDS.items():
        current = _native_scalar(profile.get(key))
        if current not in {option[0] for option in options}:
            continue
        result[key] = {"category": category, "label": label, "kind": "choice",
                       "options": [{"value": value, "label": text} for value, text in options],
                       "current": current, "level": "basic" if key in BASIC_FIELDS else "advanced",
                       "section": SECTION_FOR.get(key, "Advanced")}
    for key, (category, label) in TOGGLE_FIELDS.items():
        current = _native_scalar(profile.get(key))
        if current not in ("0", "1"):
            continue
        result[key] = {"category": category, "label": label, "kind": "toggle",
                       "options": [{"value": "0", "label": "Off"}, {"value": "1", "label": "On"}],
                       "current": current}
    return result


def validate_process_overrides(overrides):
    if overrides in (None, {}):
        return {}
    if not isinstance(overrides, dict) or len(overrides) > len(ALL_FIELDS):
        raise ValueError("Invalid native process overrides.")
    validated = {}
    for key, value in overrides.items():
        if key in CHOICE_FIELDS:
            choices = {item[0] for item in CHOICE_FIELDS[key][2]}
            if not isinstance(value, str) or value not in choices:
                raise ValueError("Unsupported native process choice.")
            validated[key] = value
        elif key in TOGGLE_FIELDS:
            if not isinstance(value, str) or value not in ("0", "1"):
                raise ValueError("Unsupported native process toggle.")
            validated[key] = value
        elif key in PROCESS_FIELDS:
            if isinstance(value, bool) or not isinstance(value, (float, int)):
                raise ValueError("Unsupported native process setting.")
            if not math.isfinite(value):
                raise ValueError("Native process settings must be finite.")
            _, _, _, lo, hi, integer = PROCESS_FIELDS[key]
            if not lo <= value <= hi or (integer and not float(value).is_integer()):
                raise ValueError("Native process setting is outside its permitted range.")
            validated[key] = int(value) if integer else round(float(value), 4)
        else:
            raise ValueError("Unsupported native process setting.")
    return validated


def apply_process_overrides(raw, overrides):
    validated = validate_process_overrides(overrides)
    if not validated:
        return raw
    try:
        profile = _check_orca_json(raw.decode("utf-8-sig"))
    except (UnicodeDecodeError, ValueError):
        raise ValueError("Native process profile could not be read.") from None
    available = process_schema(raw)
    if set(validated) - set(available):
        raise ValueError("A selected native process setting is unavailable in this profile.")
    for key, number in validated.items():
        previous = profile[key]
        formatted = (number if isinstance(number, str) else (str(int(number)) if float(number).is_integer() else str(number)) + ("%" if key == "sparse_infill_density" else ""))
        profile[key] = [formatted for _ in previous] if isinstance(previous, list) else formatted
    output = json.dumps(profile, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    if len(output) > 1024 * 1024:
        raise ValueError("Updated native process profile exceeds its size limit.")
    _check_orca_json(output.decode("utf-8"))
    return output
