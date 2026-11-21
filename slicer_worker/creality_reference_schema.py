"""Sanitised schema extracted from a native Creality Print 7.3.2.6412 K2 3MF.

This is a structural fixture, NOT the user's project. No model geometry,
filament identities/colours, settings values, scripts, local paths, UUIDs,
timestamps, or raw XML are retained. Version-specific, not a 7.3.1 guarantee.
"""
REFERENCE_VERSION = "7.3.2.6412"
MEMBER_COUNT = 17
SETTING_COUNT = 672
VALUE_KIND_COUNTS = {"str": 430, "list": 242}
LIST_LENGTH_COUNTS = {0: 10, 1: 97, 2: 18, 4: 112, 8: 1, 10: 2, 16: 2}
# Only standard public Creality settings option names; values not retained.
FOUR_SLOT_KEYS = frozenset("""
activate_air_filtration activate_chamber_layer activate_chamber_temp_control
additional_cooling_fan_speed chamber_temperature close_fan_the_first_x_layers
complete_print_exhaust_fan_speed cool_cds_fan_start_at_height cool_plate_temp
cool_plate_temp_initial_layer cool_special_cds_fan_speed
cooling_perimeter_transition_distance cooling_slowdown_logic
customized_plate_temp customized_plate_temp_initial_layer
default_filament_colour during_print_exhaust_fan_speed enable_overhang_bridge_fan
enable_pressure_advance enable_special_area_additional_cooling_fan
eng_plate_temp eng_plate_temp_initial_layer epoxy_resin_plate_temp
epoxy_resin_plate_temp_initial_layer fan_cooling_layer_time fan_max_speed
fan_min_speed filament_adhesiveness_category filament_colour
filament_colour_type filament_cooling_final_speed filament_cooling_initial_speed
filament_cooling_moves filament_cost filament_density
filament_deretraction_speed filament_diameter filament_end_gcode
filament_extruder_variant filament_flow_ratio filament_ids filament_is_support
filament_load_time filament_loading_speed filament_loading_speed_start
filament_long_retractions_when_cut filament_map filament_map_2
filament_max_volumetric_speed filament_minimal_purge_on_wipe_tower
filament_multi_colour filament_multitool_ramming filament_multitool_ramming_flow
filament_multitool_ramming_volume filament_notes filament_nozzle_variant
filament_pre_flush_speed_ratio filament_pre_flush_volume
filament_ramming_parameters filament_retract_before_wipe
filament_retract_length_toolchange filament_retract_lift_above
filament_retract_lift_below filament_retract_lift_enforce
filament_retract_restart_extra filament_retract_restart_extra_toolchange
filament_retract_when_changing_layer filament_retraction_distances_when_cut
filament_retraction_length filament_retraction_minimum_travel
filament_retraction_speed filament_settings_id filament_shrink
filament_shrinkage_compensation_z filament_soluble filament_stamping_distance
filament_stamping_loading_speed filament_start_gcode filament_toolchange_delay
filament_type filament_unload_time filament_unloading_speed
filament_unloading_speed_start filament_vendor filament_volume_map
filament_wipe filament_wipe_distance filament_z_hop filament_z_hop_types
full_fan_speed_layer hot_plate_temp hot_plate_temp_initial_layer idle_temperature
material_flow_dependent_temperature nozzle_temperature nozzle_temperature_initial_layer
nozzle_temperature_range_high nozzle_temperature_range_low overhang_fan_speed
overhang_fan_threshold pellet_flow_coefficient pressure_advance printable_area
reduce_fan_stop_start_freq required_nozzle_HRC slow_down_for_layer_cooling
slow_down_layer_time slow_down_min_speed support_material_interface_fan_speed
temperature_vitrification textured_plate_temp textured_plate_temp_initial_layer
""".split())
KNOWN_SHAPES = {
    **{key: "list:4:str" for key in FOUR_SLOT_KEYS},
    "flush_volumes_matrix": "list:16:str",
    "transmittance_matrix": "list:16:str",
    "flush_volumes_vector": "list:8:str",
    "nozzle_diameter": "list:1:str",
    "filament_map_mode": "str",
    "enable_prime_tower": "str",
    "prime_tower_width": "str",
    "wipe_tower_x": "list:1:str",
    "wipe_tower_y": "list:1:str",
    "version": "str",
    "name": "str",
    "from": "str",
}
ARCHIVE_ROLE_COUNTS = {
    "content-types": 1, "relationships": 2, "3d-model": 3,
    "project-settings": 1, "model-settings": 1, "creality-metadata": 1,
    "other-metadata": 8,
}
STRUCTURE_COUNTS = {
    "model_documents": 3, "resource_objects": 3, "meshes": 1,
    "component_groups": 2, "component_links": 2, "build_items": 2,
    "object_records": 2, "part_records": 2, "plates": 1,
    "model_instances": 2, "assembly_items": 2, "relationships": 3,
}
