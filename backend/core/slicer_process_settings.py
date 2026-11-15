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
    # Verified against OrcaSlicer 2.4.2's official Creality K2 process preset.
    "infill_direction": ("Strength", "Sparse infill direction", "°", -360, 360, False),
    "top_solid_infill_flow_ratio": ("Quality", "Top surface flow ratio", "", 0.5, 2, False),
    "bottom_solid_infill_flow_ratio": ("Quality", "Bottom surface flow ratio", "", 0.5, 2, False),
    "print_flow_ratio": ("Quality", "Print flow ratio", "", 0.5, 2, False),
    "bridge_angle": ("Quality", "External bridge angle", "°", -360, 360, False),
    "bridge_density": ("Quality", "External bridge density", "%", 0, 100, False),
    "bridge_speed": ("Speed", "External bridge speed", "mm/s", 0, 500, False),
    "overhang_totally_speed": ("Speed", "Fully unsupported overhang speed", "mm/s", 0, 500, False),
    "small_perimeter_threshold": ("Speed", "Small perimeter threshold", "mm", 0, 100, False),
    "outer_wall_jerk": ("Speed", "Outer wall jerk", "mm/s", 0, 100, False),
    "inner_wall_jerk": ("Speed", "Inner wall jerk", "mm/s", 0, 100, False),
    "infill_jerk": ("Speed", "Infill jerk", "mm/s", 0, 100, False),
    "top_surface_jerk": ("Speed", "Top surface jerk", "mm/s", 0, 100, False),
    "initial_layer_jerk": ("Speed", "First layer jerk", "mm/s", 0, 100, False),
    "travel_jerk": ("Speed", "Travel jerk", "mm/s", 0, 100, False),
    "default_jerk": ("Speed", "Default jerk", "mm/s", 0, 100, False),
    "accel_to_decel_factor": ("Speed", "Acceleration-to-deceleration ratio", "%", 0, 100, False),
    "slow_down_layers": ("Speed", "Number of slow first layers", "layers", 0, 20, True),
    "support_expansion": ("Supports", "Support expansion", "mm", 0, 15, False),
    "raft_first_layer_expansion": ("Supports", "Raft first layer expansion", "mm", 0, 15, False),
    "raft_first_layer_density": ("Supports", "Raft first layer density", "%", 0, 100, False),
    "max_bridge_length": ("Quality", "Maximum bridge length", "mm", 0, 100, False),
    "brim_ears_detection_length": ("Others", "Brim ears detection length", "mm", 0, 30, False),
    "brim_ears_max_angle": ("Others", "Brim ears maximum angle", "°", 0, 180, False),
    "ironing_flow": ("Quality", "Ironing flow", "%", 0, 100, False),
    "ironing_spacing": ("Quality", "Ironing spacing", "mm", 0.01, 5, False),
    "ironing_speed": ("Quality", "Ironing speed", "mm/s", 0, 200, False),
    "ironing_inset": ("Quality", "Ironing inset", "mm", 0, 10, False),
    "ironing_angle": ("Quality", "Ironing angle offset", "°", -360, 360, False),
    "zaa_minimize_perimeter_height": ("Quality", "Minimize wall height angle", "°", 0, 90, False),
    "zaa_min_z": ("Quality", "Minimum Z height", "mm", 0, 2, False),

    # Additional documented native Orca process settings; only keys actually
    # present in an inspected resolved preset are exposed to editing.
    "bridge_line_width": ("Quality", "Bridge line width", "mm", 0.1, 2, False),
    "seam_gap": ("Quality", "Seam gap", "%", 0, 100, False),
    "scarf_joint_flow_ratio": ("Quality", "Scarf joint flow ratio", "%", 0, 200, False),
    "wipe_speed": ("Quality", "Wipe speed", "mm/s", 0, 500, False),
    "wall_transition_angle": ("Quality", "Wall transition angle", "°", 0, 90, False),
    "wall_transition_filter_deviation": ("Quality", "Wall transition filter deviation", "%", 0, 100, False),
    "wall_transition_length": ("Quality", "Wall transition length", "%", 0, 200, False),
    "wall_distribution_count": ("Quality", "Wall distribution count", "", 1, 20, True),
    "min_bead_width": ("Quality", "Minimum bead width", "%", 0, 100, False),
    "initial_layer_min_bead_width": ("Quality", "First layer minimum bead width", "%", 0, 100, False),
    "min_feature_size": ("Quality", "Minimum feature size", "%", 0, 200, False),
    "wall_maximum_resolution": ("Quality", "Wall maximum resolution", "mm", 0, 2, False),
    "wall_maximum_deviation": ("Quality", "Wall maximum deviation", "%", 0, 100, False),
    "max_travel_detour_distance": ("Quality", "Maximum travel detour", "mm", 0, 500, False),
    "make_overhang_printable_angle": ("Quality", "Overhang printable angle", "°", 0, 90, False),
    "make_overhang_printable_hole_size": ("Quality", "Overhang printable hole size", "mm", 0, 100, False),
    "overhang_reverse_threshold": ("Quality", "Overhang reverse threshold", "%", 0, 100, False),
    "top_bottom_infill_wall_overlap": ("Strength", "Top/bottom infill wall overlap", "%", 0, 100, False),
    "top_surface_expansion": ("Strength", "Top surface expansion", "mm", 0, 20, False),
    "top_surface_expansion_margin": ("Strength", "Top surface expansion margin", "mm", 0, 20, False),
    "fill_multiline": ("Strength", "Infill multiline count", "", 1, 10, True),
    "sparse_infill_smooth_factor": ("Strength", "Infill smoothing factor", "%", 0, 100, False),
    "infill_combination_max_layer_height": ("Strength", "Maximum combined infill layer height", "mm", 0, 2, False),
    "initial_layer_travel_speed": ("Speed", "First layer travel speed", "mm/s", 0, 1000, False),
    "small_perimeter_speed": ("Speed", "Small perimeter speed", "mm/s", 0, 500, False),
    "small_support_perimeter_speed": ("Speed", "Small support perimeter speed", "mm/s", 0, 500, False),
    "small_support_perimeter_threshold": ("Speed", "Small support perimeter threshold", "mm", 0, 100, False),
    "bridge_acceleration": ("Speed", "Bridge acceleration", "mm/s²", 0, 30000, False),
    "sparse_infill_acceleration": ("Speed", "Sparse infill acceleration", "mm/s²", 0, 30000, False),
    "internal_solid_infill_acceleration": ("Speed", "Internal solid infill acceleration", "mm/s²", 0, 30000, False),
    "initial_layer_travel_acceleration": ("Speed", "First layer travel acceleration", "mm/s²", 0, 30000, False),
    "initial_layer_travel_jerk": ("Speed", "First layer travel jerk", "mm/s", 0, 100, False),
    "support_threshold_overlap": ("Supports", "Support threshold overlap", "%", 0, 100, False),
    "support_angle": ("Supports", "Support angle", "°", 0, 90, False),
    "support_object_first_layer_gap": ("Supports", "Support first layer object gap", "mm", 0, 10, False),
    "tree_support_wall_count": ("Supports", "Tree support wall loops", "", 0, 10, True),
    "tree_support_tip_diameter": ("Supports", "Tree support tip diameter", "mm", 0, 20, False),
    "tree_support_top_rate": ("Supports", "Tree support top rate", "%", 0, 100, False),
    "tree_support_branch_diameter_angle": ("Supports", "Tree branch diameter angle", "°", 0, 90, False),
    "tree_support_angle_slow": ("Supports", "Tree support slow angle", "°", 0, 90, False),
    "tree_support_brim_width": ("Supports", "Tree support brim width", "mm", 0, 50, False),
    "support_ironing_flow": ("Supports", "Support ironing flow", "%", 0, 100, False),
    "support_ironing_spacing": ("Supports", "Support ironing spacing", "mm", 0.01, 5, False),
    "prime_tower_width": ("Multifilament", "Prime tower width", "mm", 0, 300, False),
    "prime_volume": ("Multifilament", "Prime volume", "mm³", 0, 1000, False),
    "prime_tower_brim_width": ("Multifilament", "Prime tower brim width", "mm", 0, 50, False),
    "prime_tower_infill_gap": ("Multifilament", "Prime tower infill gap", "mm", 0, 20, False),
    "wipe_tower_rotation_angle": ("Multifilament", "Wipe tower rotation", "°", -360, 360, False),
    "wipe_tower_extra_spacing": ("Multifilament", "Wipe tower purge spacing", "mm", 0, 20, False),
    "wipe_tower_extra_flow": ("Multifilament", "Extra purge flow", "%", 0, 200, False),
    "wipe_tower_max_purge_speed": ("Multifilament", "Maximum tower purge speed", "mm/s", 0, 500, False),
    "standby_temperature_delta": ("Multifilament", "Standby temperature change", "°C", -100, 100, False),
    "preheat_time": ("Multifilament", "Preheat time", "s", 0, 1000, False),
    "preheat_steps": ("Multifilament", "Preheat steps", "", 0, 100, True),
    "skirt_start_angle": ("Others", "Skirt start angle", "°", -360, 360, False),
    "min_skirt_length": ("Others", "Minimum skirt length", "mm", 0, 1000, False),
    "leading_brim_length": ("Others", "Leading brim length", "mm", 0, 1000, False),
    "extra_brim_width": ("Others", "Extra brim width", "mm", 0, 100, False),
    "spiral_mode_max_xy_smoothing": ("Others", "Spiral smoothing distance", "mm", 0, 100, False),
    "spiral_starting_flow_ratio": ("Others", "Spiral starting flow", "%", 0, 200, False),
    "spiral_finishing_flow_ratio": ("Others", "Spiral finishing flow", "%", 0, 200, False),
    "fuzzy_skin_scale": ("Others", "Fuzzy skin scale", "", 0, 100, False),
    "fuzzy_skin_octaves": ("Others", "Fuzzy skin octaves", "", 1, 20, True),
    "fuzzy_skin_persistence": ("Others", "Fuzzy skin persistence", "", 0, 1, False),
    "exclude_object_tolerance": ("Others", "Exclude object tolerance", "mm", 0, 100, False),

}


# Only recognised, existing Orca enum values may be replaced.
CHOICE_FIELDS = {
    "sparse_infill_pattern": ("Strength", "Sparse infill pattern", (
        ("grid", "Grid"), ("gyroid", "Gyroid"), ("rectilinear", "Rectilinear"),
        ("crosshatch", "Crosshatch"), ("triangles", "Triangles"),
        ("honeycomb", "Honeycomb"), ("cubic", "Cubic"),
        ("alignedrectilinear", "Aligned rectilinear"), ("zigzag", "Zigzag"),
        ("line", "Line"), ("tri-hexagon", "Tri-hexagon"),
        ("adaptivecubic", "Adaptive cubic"), ("quartercubic", "Quarter cubic"),
        ("supportcubic", "Support cubic"), ("lightning", "Lightning"),
        ("3dhoneycomb", "3D honeycomb"), ("concentric", "Concentric"),
        ("hilbertcurve", "Hilbert curve"), ("archimedeanchords", "Archimedean chords"),
        ("octagramspiral", "Octagram spiral"),
    )),
    "seam_position": ("Quality", "Seam position", (
        ("aligned", "Aligned"), ("nearest", "Nearest"), ("rear", "Rear"),
        ("random", "Random"),
    )),
    "wall_generator": ("Quality", "Wall generator", (
        ("classic", "Classic"), ("arachne", "Arachne"),
    )),
    "top_surface_pattern": ("Strength", "Top surface pattern", (
        ("monotonicline", "Monotonic lines"), ("monotonic", "Monotonic"),
        ("rectilinear", "Rectilinear"), ("concentric", "Concentric"),
    )),
    "bottom_surface_pattern": ("Strength", "Bottom surface pattern", (
        ("monotonicline", "Monotonic lines"), ("monotonic", "Monotonic"),
        ("rectilinear", "Rectilinear"), ("concentric", "Concentric"),
    )),
    "internal_solid_infill_pattern": ("Strength", "Internal solid infill pattern", (
        ("monotonic", "Monotonic"), ("rectilinear", "Rectilinear"),
        ("concentric", "Concentric"), ("monotonicline", "Monotonic lines"),
    )),
    "ironing_type": ("Quality", "Ironing type", (
        ("no ironing", "No ironing"), ("top", "All top surfaces"),
        ("topmost", "Topmost surface only"), ("solid", "All solid layers"),
    )),
    "ironing_pattern": ("Quality", "Ironing pattern", (
        ("rectilinear", "Rectilinear"), ("concentric", "Concentric"),
    )),
    "wall_sequence": ("Quality", "Wall printing order", (
        ("inner wall/outer wall", "Inner/outer"), ("outer wall/inner wall", "Outer/inner"),
        ("inner-outer-inner wall", "Inner/outer/inner"),
    )),
    "wall_direction": ("Quality", "Wall direction", (
        ("ccw", "Counter-clockwise"), ("cw", "Clockwise"),
    )),
    "gap_fill_target": ("Strength", "Gap fill target", (
        ("everywhere", "Everywhere"), ("topbottom", "Top/bottom"), ("nowhere", "Nowhere"),
    )),
    "support_style": ("Supports", "Support style", (
        ("default", "Default"), ("grid", "Grid"), ("snug", "Snug"),
        ("organic", "Organic"), ("tree_slim", "Tree slim"),
        ("tree_strong", "Tree strong"), ("tree_hybrid", "Tree hybrid"),
    )),
    "support_base_pattern": ("Supports", "Base support pattern", (
        ("default", "Default"), ("rectilinear", "Rectilinear"),
        ("rectilinear-grid", "Rectilinear grid"), ("honeycomb", "Honeycomb"),
        ("lightning", "Lightning"), ("hollow", "Hollow"),
    )),
    "support_interface_pattern": ("Supports", "Support interface pattern", (
        ("auto", "Auto"), ("rectilinear", "Rectilinear"),
        ("concentric", "Concentric"), ("spiralinset", "Spiral inset"),
        ("rectilinear_interlaced", "Interlaced"), ("grid", "Grid"),
    )),
    "support_ironing_pattern": ("Supports", "Support ironing pattern", (
        ("rectilinear", "Rectilinear"), ("concentric", "Concentric"),
    )),
    "fuzzy_skin": ("Others", "Fuzzy skin", (
        ("none", "Off"), ("external", "External"), ("hole", "Holes"),
        ("all", "All"), ("allwalls", "All walls"), ("disabled_fuzzy", "Disabled fuzzy"),
    )),
    "fuzzy_skin_mode": ("Others", "Fuzzy skin mode", (
        ("displacement", "Displacement"), ("extrusion", "Extrusion"),
        ("combined", "Combined"),
    )),
    "fuzzy_skin_noise_type": ("Others", "Fuzzy skin noise type", (
        ("classic", "Classic"), ("perlin", "Perlin"), ("billow", "Billow"),
        ("ridgedmulti", "Ridged multifractal"), ("voronoi", "Voronoi"),
        ("ripple", "Ripple"),
    )),
    "brim_type": ("Others", "Brim type", (
        ("auto_brim", "Auto"), ("brim_ears", "Brim ears"),
        ("painted", "Painted"), ("outer_only", "Outer only"),
        ("inner_only", "Inner only"), ("outer_and_inner", "Outer and inner"),
        ("no_brim", "No brim"), ("leading_edge_only", "Leading edge only"),
    )),
    "skirt_type": ("Others", "Skirt type", (
        ("combined", "Combined"), ("perobject", "Per object"),
    )),
    "draft_shield": ("Others", "Draft shield", (
        ("disabled", "Disabled"), ("enabled", "Enabled"),
    )),
    "slicing_mode": ("Others", "Slicing mode", (
        ("regular", "Regular"), ("even_odd", "Even-odd"), ("close_holes", "Close holes"),
    )),
    "print_sequence": ("Others", "Print sequence", (
        ("by layer", "By layer"), ("by object", "By object"),
    )),
    "print_order": ("Others", "Intra-layer order", (
        ("default", "Default"), ("as_obj_list", "Object list"),
        ("best_of", "Best of"), ("snake", "Snake"),
    )),
    "support_type": ("Supports", "Support type", (
        ("normal(auto)", "Normal (auto)"), ("normal(manual)", "Normal (manual)"),
        ("tree(auto)", "Tree (auto)"), ("tree(manual)", "Tree (manual)"),
    )),

}
TOGGLE_FIELDS = {
    "ironing_angle_fixed": ("Quality", "Fixed ironing angle"),
    "zaa_enabled": ("Quality", "Enable Z contouring"),
    "zaa_dont_alternate_fill_direction": ("Quality", "Keep contour fill direction"),
    "enable_support": ("Supports", "Generate supports"),
    "support_on_build_plate_only": ("Supports", "On build plate only"),
    "support_remove_small_overhang": ("Supports", "Ignore small overhangs"),
    "detect_thin_wall": ("Strength", "Detect thin walls"),
    "alternate_extra_wall": ("Strength", "Alternate extra wall"),
    "infill_combination": ("Strength", "Infill combination"),
    "spiral_mode": ("Others", "Spiral vase"),
    "support_ironing": ("Supports", "Ironing support interface"),
    "make_overhang_printable": ("Quality", "Make overhang printable"),
    "unsupported_wall_last": ("Quality", "Print unsupported walls last"),
    "overhang_reverse": ("Quality", "Reverse overhang direction"),
    "separated_infills": ("Strength", "Separated infills"),
    "independent_support_layer_height": ("Supports", "Independent support layer height"),
    "tree_support_auto_brim": ("Supports", "Automatic tree support brim"),
    "enable_prime_tower": ("Multifilament", "Enable prime tower"),
    "enable_tower_interface_features": ("Multifilament", "Tower interface features"),
    "prime_tower_enable_framework": ("Multifilament", "Prime tower internal ribs"),
    "flush_into_infill": ("Multifilament", "Flush into infill"),
    "flush_into_objects": ("Multifilament", "Flush into objects"),
    "flush_into_support": ("Multifilament", "Flush into support"),
    "ooze_prevention": ("Multifilament", "Ooze prevention"),
    "brim_ears_outer_only": ("Others", "Brim ears outer only"),
    "combine_brims": ("Others", "Combine brims"),
    "single_loop_draft_shield": ("Others", "Single loop draft shield"),
    "spiral_mode_smooth": ("Others", "Smooth spiral mode"),
    "enable_wrapping_detection": ("Others", "Clumping detection"),
    "fuzzy_skin_first_layer": ("Others", "Fuzzy skin on first layer"),
    "reduce_infill_retraction": ("Others", "Reduce infill retraction"),
    "enable_arc_fitting": ("Quality", "Arc fitting"),
    "staggered_inner_seams": ("Quality", "Staggered inner seams"),
    "only_one_wall_first_layer": ("Quality", "Only one wall on first layer"),
    "only_one_wall_top": ("Quality", "Only one wall on top surfaces"),
    "is_infill_first": ("Quality", "Print infill first"),
    "precise_outer_wall": ("Quality", "Precise wall"),
    "detect_overhang_wall": ("Quality", "Detect overhang walls"),
    "extra_perimeters_on_overhangs": ("Quality", "Extra perimeters on overhangs"),
    "thick_bridges": ("Quality", "Thick external bridges"),
    "thick_internal_bridges": ("Quality", "Thick internal bridges"),
    "reduce_crossing_wall": ("Quality", "Avoid crossing walls"),
    "wipe_on_loops": ("Quality", "Wipe on loops"),
    "wipe_before_external_loop": ("Quality", "Wipe before external loop"),
    "role_based_wipe_speed": ("Quality", "Role-based wipe speed"),
    "detect_narrow_internal_solid_infill": ("Strength", "Detect narrow internal solid infills"),
    "bridge_no_support": ("Supports", "Don't support bridges"),
    "support_critical_regions_only": ("Supports", "Critical support regions only"),
    "support_interface_not_for_body": ("Supports", "Interface only near supported features"),
    "enable_overhang_speed": ("Speed", "Slow down for overhangs"),
    "slowdown_for_curled_perimeters": ("Speed", "Slow down for curled perimeters"),
    "accel_to_decel_enable": ("Speed", "Enable acceleration to deceleration"),
    "gcode_comments": ("Others", "Verbose G-code"),
    "gcode_label_objects": ("Others", "Label objects"),
    "exclude_object": ("Others", "Exclude objects"),

}
ALL_FIELDS = set(PROCESS_FIELDS) | set(CHOICE_FIELDS) | set(TOGGLE_FIELDS)

# Curated from OrcaSlicer process panels. Basic contains ordinary, frequently
# adjusted print outcomes. All other supported fields appear in Advanced.
EXPERT_FIELDS = frozenset({
    "zaa_enabled", "zaa_minimize_perimeter_height", "zaa_min_z",
    "zaa_dont_alternate_fill_direction", "wall_transition_filter_deviation",
    "wall_maximum_resolution", "wall_maximum_deviation",
    "prime_tower_enable_framework", "overhang_reverse_threshold",
})
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
        "Seam": {"seam_position", "staggered_inner_seams", "role_based_wipe_speed",
                 "wipe_on_loops", "wipe_before_external_loop"},
        "Precision": {"slice_closing_radius", "resolution", "xy_hole_compensation",
                       "xy_contour_compensation", "elefant_foot_compensation",
                       "elefant_foot_compensation_layers", "enable_arc_fitting"},
        "Walls and surfaces": {"top_surface_flow_ratio", "bottom_surface_flow_ratio",
                               "top_solid_infill_flow_ratio", "bottom_solid_infill_flow_ratio",
                               "print_flow_ratio", "wall_generator",
                               "only_one_wall_first_layer", "only_one_wall_top",
                               "is_infill_first", "precise_outer_wall", "reduce_crossing_wall"},
        "Bridging": {"bridge_flow", "internal_bridge_flow", "bridge_angle",
                     "bridge_density", "max_bridge_length", "thick_bridges",
                     "thick_internal_bridges", "detect_overhang_wall",
                     "extra_perimeters_on_overhangs"},
        "Fuzzy skin": {"fuzzy_skin_point_distance", "fuzzy_skin_thickness", "fuzzy_skin_first_layer"},
        "Ironing": {"ironing_type", "ironing_pattern", "ironing_flow", "ironing_spacing",
                    "ironing_speed", "ironing_inset", "ironing_angle", "ironing_angle_fixed"},
        "Z contouring": {"zaa_enabled", "zaa_minimize_perimeter_height", "zaa_min_z",
                         "zaa_dont_alternate_fill_direction"},
    },
    "Strength": {
        "Walls": {"wall_loops", "detect_thin_wall", "alternate_extra_wall"},
        "Top/bottom shells": {"top_shell_layers", "bottom_shell_layers",
                              "top_shell_thickness", "bottom_shell_thickness",
                              "top_surface_density", "bottom_surface_density",
                              "top_surface_pattern", "bottom_surface_pattern"},
        "Infill": {"sparse_infill_density", "sparse_infill_pattern",
                   "internal_solid_infill_pattern", "infill_direction",
                   "sparse_infill_direction", "solid_infill_direction",
                   "infill_wall_overlap", "infill_combination",
                   "minimum_sparse_infill_area", "sparse_infill_line_width"},
    },
    "Speed": {
        "First layer speed": {"initial_layer_speed", "initial_layer_infill_speed", "slow_down_layers"},
        "Other layers speed": {"outer_wall_speed", "inner_wall_speed",
                               "sparse_infill_speed", "internal_solid_infill_speed",
                               "top_surface_speed", "gap_infill_speed", "bridge_speed",
                               "overhang_totally_speed", "small_perimeter_threshold",
                               "enable_overhang_speed", "slowdown_for_curled_perimeters"},
        "Travel speed": {"travel_speed"},
        "Acceleration": {"default_acceleration", "outer_wall_acceleration",
                         "inner_wall_acceleration", "initial_layer_acceleration",
                         "accel_to_decel_enable", "accel_to_decel_factor",
                         "top_surface_acceleration", "travel_acceleration"},
        "Jerk (XY)": {"default_jerk", "outer_wall_jerk", "inner_wall_jerk",
                      "infill_jerk", "top_surface_jerk", "initial_layer_jerk",
                      "travel_jerk"},
    },
    "Supports": {
        "Support": {"enable_support", "support_threshold_angle",
                    "support_on_build_plate_only", "support_remove_small_overhang",
                    "support_type", "support_critical_regions_only"},
        "Raft": {"raft_layers", "raft_first_layer_density", "raft_first_layer_expansion"},
        "Support ironing": {"support_ironing", "support_ironing_pattern",
                            "support_ironing_flow", "support_ironing_spacing"},
        "Advanced": {"support_top_z_distance", "support_bottom_z_distance",
                     "support_wall_loops", "support_base_pattern_spacing",
                     "support_interface_top_layers", "support_interface_bottom_layers",
                     "support_interface_spacing", "support_bottom_interface_spacing",
                     "support_object_xy_distance", "support_speed",
                     "support_interface_speed", "support_expansion", "bridge_no_support",
                     "support_interface_not_for_body"},
    },
    "Others": {
        "Skirt": {"skirt_loops", "skirt_distance", "skirt_height", "skirt_speed"},
        "Brim": {"brim_width", "brim_object_gap", "brim_flow_ratio",
                 "brim_ears_detection_length", "brim_ears_max_angle"},
        "Special mode": {"spiral_mode"},
        "G-code output": {"reduce_infill_retraction", "gcode_comments",
                          "gcode_label_objects", "exclude_object"},
    },
}

# Build the workbench's categories from Orca's native process groupings.
# Unrecognised keys are not made editable; recognised keys lacking a custom
# subgroup are still grouped under their correct category.
SECTIONS["Quality"]["Seam"].update({"seam_gap", "scarf_joint_flow_ratio", "wipe_speed"})
SECTIONS["Quality"]["Line width"].update({"bridge_line_width"})
SECTIONS["Quality"]["Walls and surfaces"].update({
    "wall_sequence", "wall_direction", "wall_transition_angle",
    "wall_transition_filter_deviation", "wall_transition_length",
    "wall_distribution_count", "min_bead_width", "initial_layer_min_bead_width",
    "min_feature_size", "wall_maximum_resolution", "wall_maximum_deviation",
    "max_travel_detour_distance",
})
SECTIONS["Quality"]["Overhangs"] = {
    "detect_overhang_wall", "make_overhang_printable",
    "make_overhang_printable_angle", "make_overhang_printable_hole_size",
    "unsupported_wall_last", "extra_perimeters_on_overhangs",
    "overhang_reverse", "overhang_reverse_threshold",
}
SECTIONS["Strength"]["Top/bottom shells"].update({
    "top_bottom_infill_wall_overlap", "top_surface_expansion",
    "top_surface_expansion_margin",
})
SECTIONS["Strength"]["Infill"].update({
    "fill_multiline", "sparse_infill_smooth_factor", "gap_fill_target",
    "separated_infills", "infill_combination_max_layer_height",
})
SECTIONS["Speed"]["First layer speed"].update({"initial_layer_travel_speed"})
SECTIONS["Speed"]["Other layers speed"].update({
    "small_perimeter_speed", "small_support_perimeter_speed",
    "small_support_perimeter_threshold",
})
SECTIONS["Speed"]["Acceleration"].update({
    "bridge_acceleration", "sparse_infill_acceleration",
    "internal_solid_infill_acceleration", "initial_layer_travel_acceleration",
})
SECTIONS["Speed"]["Jerk (XY)"].update({"initial_layer_travel_jerk"})
SECTIONS["Supports"]["Support"].update({
    "support_style", "support_threshold_overlap", "support_angle",
})
SECTIONS["Supports"]["Advanced"].update({
    "support_base_pattern", "support_interface_pattern",
    "support_object_first_layer_gap", "independent_support_layer_height",
})
SECTIONS["Supports"]["Tree support"] = {
    "tree_support_wall_count", "tree_support_tip_diameter",
    "tree_support_top_rate", "tree_support_branch_diameter_angle",
    "tree_support_angle_slow", "tree_support_auto_brim",
    "tree_support_brim_width",
}
SECTIONS["Multifilament"] = {
    "Prime tower": {"enable_prime_tower", "prime_tower_width", "prime_volume",
                    "prime_tower_brim_width", "prime_tower_infill_gap",
                    "wipe_tower_rotation_angle", "wipe_tower_extra_spacing",
                    "wipe_tower_extra_flow", "wipe_tower_max_purge_speed",
                    "enable_tower_interface_features", "prime_tower_enable_framework"},
    "Flush options": {"flush_into_infill", "flush_into_objects", "flush_into_support"},
    "Ooze prevention": {"ooze_prevention", "standby_temperature_delta",
                        "preheat_time", "preheat_steps"},
}
SECTIONS["Others"]["Skirt"].update({"skirt_type", "draft_shield",
                                     "single_loop_draft_shield",
                                     "skirt_start_angle", "min_skirt_length"})
SECTIONS["Others"]["Brim"].update({"brim_type", "brim_ears_outer_only",
                                    "combine_brims", "leading_brim_length",
                                    "extra_brim_width"})
SECTIONS["Others"]["Special mode"].update({
    "slicing_mode", "print_sequence", "print_order", "spiral_mode_smooth",
    "spiral_mode_max_xy_smoothing", "spiral_starting_flow_ratio",
    "spiral_finishing_flow_ratio", "enable_wrapping_detection",
})
SECTIONS["Others"]["Fuzzy skin"] = {
    "fuzzy_skin", "fuzzy_skin_mode", "fuzzy_skin_noise_type",
    "fuzzy_skin_point_distance", "fuzzy_skin_thickness",
    "fuzzy_skin_scale", "fuzzy_skin_octaves", "fuzzy_skin_persistence",
    "fuzzy_skin_first_layer",
}
SECTIONS["Others"]["G-code output"].update({"exclude_object_tolerance"})

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


def _scalar(value, unit=""):
    if isinstance(value, list):
        if not value or len(value) > 8 or any(item != value[0] for item in value):
            return None
        value = value[0]
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        return None
    if isinstance(value, str) and value.strip().endswith("%") and unit != "%":
        return None  # Do not treat percentages as dimensional measurements.
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
        current = _scalar(profile[key], unit)
        if current is None or not lo <= current <= hi:
            continue
        result[key] = {
            "category": category, "label": label, "unit": unit,
            "minimum": lo, "maximum": hi, "integer": integer,
            "current": current, "level": "basic" if key in BASIC_FIELDS else ("expert" if key in EXPERT_FIELDS else "advanced"),
            "section": SECTION_FOR.get(key, "Advanced"),
        }
    for key, (category, label, options) in CHOICE_FIELDS.items():
        current = _native_scalar(profile.get(key))
        if current not in {option[0] for option in options}:
            continue
        result[key] = {"category": category, "label": label, "kind": "choice",
                       "options": [{"value": value, "label": text} for value, text in options],
                       "current": current, "level": "basic" if key in BASIC_FIELDS else ("expert" if key in EXPERT_FIELDS else "advanced"),
                       "section": SECTION_FOR.get(key, "Advanced")}
    for key, (category, label) in TOGGLE_FIELDS.items():
        current = _native_scalar(profile.get(key))
        if current not in ("0", "1"):
            continue
        result[key] = {"category": category, "label": label, "kind": "toggle",
                       "options": [{"value": "0", "label": "Off"}, {"value": "1", "label": "On"}],
                       "current": current, "level": "basic" if key in BASIC_FIELDS else ("expert" if key in EXPERT_FIELDS else "advanced"),
                       "section": SECTION_FOR.get(key, "Advanced")}
    # Conditional visibility is driven by actual native controls. Never expose a
    # synthetic enable switch when the resolved profile has no matching key.
    # A dependent is visible only while the *native* feature is enabled.
    # These relationships are descriptive: the original preset still provides
    # the canonical defaults and all values remain validated before slicing.
    dependencies = {
        "ironing_type": ("ironing_pattern", "ironing_flow", "ironing_spacing",
                         "ironing_speed", "ironing_inset", "ironing_angle",
                         "ironing_angle_fixed"),
        "zaa_enabled": ("zaa_minimize_perimeter_height", "zaa_min_z",
                        "zaa_dont_alternate_fill_direction"),
        "enable_support": ("tree_support_wall_count", "tree_support_tip_diameter",
                           "tree_support_top_rate", "tree_support_branch_diameter_angle",
                           "tree_support_angle_slow", "tree_support_auto_brim",
                           "tree_support_brim_width",
                           "support_threshold_angle", "support_threshold_overlap",
                           "support_style", "support_on_build_plate_only",
                           "support_remove_small_overhang", "support_type",
                           "support_critical_regions_only", "support_top_z_distance",
                           "support_bottom_z_distance", "support_interface_top_layers",
                           "support_interface_bottom_layers", "support_interface_spacing",
                           "support_bottom_interface_spacing", "support_object_xy_distance",
                           "support_speed", "support_interface_speed", "support_expansion",
                           "support_base_pattern", "support_interface_pattern",
                           "support_object_first_layer_gap", "support_angle",
                           "independent_support_layer_height", "bridge_no_support"),
        "enable_prime_tower": ("prime_tower_width", "prime_volume",
                               "prime_tower_brim_width", "prime_tower_infill_gap",
                               "wipe_tower_rotation_angle", "wipe_tower_extra_spacing",
                               "wipe_tower_extra_flow", "wipe_tower_max_purge_speed",
                               "enable_tower_interface_features",
                               "prime_tower_enable_framework"),
        "ooze_prevention": ("standby_temperature_delta", "preheat_time", "preheat_steps"),
        "fuzzy_skin": ("fuzzy_skin_mode", "fuzzy_skin_noise_type",
                       "fuzzy_skin_point_distance", "fuzzy_skin_thickness",
                       "fuzzy_skin_scale", "fuzzy_skin_octaves",
                       "fuzzy_skin_persistence", "fuzzy_skin_first_layer"),
        "spiral_mode": ("spiral_mode_smooth", "spiral_mode_max_xy_smoothing",
                        "spiral_starting_flow_ratio", "spiral_finishing_flow_ratio"),
        "make_overhang_printable": ("make_overhang_printable_angle",
                                    "make_overhang_printable_hole_size"),
        "support_ironing": ("support_ironing_pattern", "support_ironing_flow",
                            "support_ironing_spacing"),
        "accel_to_decel_enable": ("accel_to_decel_factor",),
        "wall_generator": ("wall_transition_angle", "wall_transition_filter_deviation",
                           "wall_transition_length", "wall_distribution_count",
                           "min_bead_width", "initial_layer_min_bead_width",
                           "min_feature_size", "wall_maximum_resolution",
                           "wall_maximum_deviation"),
    }
    for master, dependents in dependencies.items():
        if master not in result:
            continue
        for dependent in dependents:
            if dependent in result:
                if master == "wall_generator":
                    condition = {"key": master, "in": ["arachne"]}
                elif master == "fuzzy_skin":
                    condition = {"key": master, "in": ["external", "hole", "all", "allwalls"]}
                else:
                    disabled = "no ironing" if master == "ironing_type" else "0"
                    condition = {"key": master, "not": disabled}
                previous = result[dependent].get("enabled_when")
                result[dependent]["enabled_when"] = [previous, condition] if previous else condition
    # Nested dependencies use an array to preserve every enabling condition.
    nested = {
        "ironing_pattern": ("ironing_angle", "ironing_angle_fixed"),
        "support_type": ("tree_support_wall_count", "tree_support_tip_diameter",
                         "tree_support_top_rate", "tree_support_branch_diameter_angle",
                         "tree_support_angle_slow", "tree_support_auto_brim",
                         "tree_support_brim_width"),
        "brim_type": ("brim_ears_max_angle", "brim_ears_detection_length",
                      "brim_ears_outer_only"),
    }
    for master, dependents in nested.items():
        if master not in result:
            continue
        for dependent in dependents:
            if dependent not in result:
                continue
            condition = ({
                "key": master, "in": ["rectilinear"]
            } if master == "ironing_pattern" else {
                "key": master, "in": ["tree(auto)", "tree(manual)"]
            } if master == "support_type" else {
                "key": master, "in": ["brim_ears"]
            })
            previous = result[dependent].get("enabled_when")
            result[dependent]["enabled_when"] = ([previous, condition] if previous else condition)
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
        previous_scalar = previous[0] if isinstance(previous, list) else previous
        suffix = "%" if key in PROCESS_FIELDS and PROCESS_FIELDS[key][2] == "%" and str(previous_scalar).strip().endswith("%") else ""
        formatted = number if isinstance(number, str) else (
            (str(int(number)) if float(number).is_integer() else str(number)) + suffix
        )
        profile[key] = [formatted for _ in previous] if isinstance(previous, list) else formatted
    output = json.dumps(profile, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    if len(output) > 1024 * 1024:
        raise ValueError("Updated native process profile exceeds its size limit.")
    _check_orca_json(output.decode("utf-8"))
    return output
