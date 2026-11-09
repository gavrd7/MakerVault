import json

from django.test import SimpleTestCase

from core.slicer_process_settings import (
    PROCESS_FIELDS, process_schema, validate_process_overrides, apply_process_overrides,
)


class NativeProcessSettingsTests(SimpleTestCase):
    def sample(self):
        return json.dumps({
            "name": "Official sample",
            "layer_height": "0.2", "initial_layer_print_height": "0.25",
            "wall_loops": "2", "top_shell_layers": "4",
            "sparse_infill_density": "15%", "outer_wall_speed": "80",
            "support_threshold_angle": "35", "brim_width": "0",
            "machine_start_gcode": "START_PRINT EXTRUDER_TEMP=220",
            "change_filament_gcode": "M600",
        }).encode("utf-8")

    def test_schema_preserves_engine_native_current_values(self):
        fields = process_schema(self.sample())
        self.assertEqual(fields["layer_height"]["current"], 0.2)
        self.assertEqual(fields["wall_loops"]["category"], "Strength")
        self.assertEqual(fields["sparse_infill_density"]["current"], 15)
        self.assertNotIn("machine_start_gcode", fields)

    def test_overrides_modify_only_selected_settings(self):
        source = self.sample()
        amended = apply_process_overrides(source, {
            "layer_height": 0.16, "wall_loops": 3, "sparse_infill_density": 20,
        })
        original = json.loads(source)
        updated = json.loads(amended)
        self.assertEqual(original["layer_height"], "0.2")
        self.assertEqual(updated["layer_height"], "0.16")
        self.assertEqual(updated["wall_loops"], "3")
        self.assertEqual(updated["sparse_infill_density"], "20%")
        self.assertEqual(updated["machine_start_gcode"], original["machine_start_gcode"])
        self.assertEqual(updated["change_filament_gcode"], original["change_filament_gcode"])
        self.assertEqual(updated["outer_wall_speed"], original["outer_wall_speed"])

    def test_missing_setting_not_fabricated(self):
        with self.assertRaises(ValueError):
            apply_process_overrides(self.sample(), {"travel_speed": 100})

    def test_rejects_invalid_or_unsafe_edits(self):
        for edits in (
            {"machine_start_gcode": "M109"},
            {"retraction_distances_when_cut": 20},
            {"wall_loops": 2.5},
            {"layer_height": -1},
            {"layer_height": float("nan")},
            {"outer_wall_speed": 10000},
            {"layer_height": "0.1"},
            {"layer_height": True},
        ):
            with self.subTest(edits=edits), self.assertRaises(ValueError):
                validate_process_overrides(edits)

    def test_all_categories_have_native_controls(self):
        categories = {spec[0] for spec in PROCESS_FIELDS.values()}
        self.assertTrue({"Quality", "Strength", "Speed", "Supports", "Others"} <= categories)

    def test_native_changes_persist_as_draft_metadata(self):
        from core.slicer_api import _draft_plate_settings
        settings = _draft_plate_settings(None, None, {
            "workflow": "interactive", "process_overrides": {
                "layer_height": 0.16, "wall_loops": 3
            },
        })
        self.assertEqual(settings["process_overrides"],
                         {"layer_height": 0.16, "wall_loops": 3})
        with self.assertRaises(ValueError):
            _draft_plate_settings(None, None, {
                "process_overrides": {"machine_start_gcode": "M600"},
            })


    def test_ironing_native_mode_and_dependent_values(self):
        source = json.dumps({
            "name": "Orca process", "ironing_type": "no ironing",
            "ironing_pattern": "rectilinear", "ironing_flow": "10%",
            "ironing_spacing": "0.15", "machine_start_gcode": "START_PRINT",
        }).encode()
        fields = process_schema(source)
        self.assertEqual(fields["ironing_type"]["kind"], "choice")
        self.assertEqual(fields["ironing_flow"]["enabled_when"],
                         {"key": "ironing_type", "not": "no ironing"})
        updated = json.loads(apply_process_overrides(source, {
            "ironing_type": "topmost", "ironing_flow": 12,
        }))
        self.assertEqual(updated["ironing_type"], "topmost")
        self.assertEqual(updated["ironing_flow"], "12%")
        self.assertEqual(updated["machine_start_gcode"], "START_PRINT")
        self.assertNotIn("zaa_enabled", fields)

    def test_z_contouring_native_switch_and_dependent_values(self):
        source = json.dumps({
            "name": "Orca process", "zaa_enabled": "0",
            "zaa_minimize_perimeter_height": "35",
            "zaa_min_z": "0.1",
            "zaa_dont_alternate_fill_direction": "0",
        }).encode()
        fields = process_schema(source)
        self.assertEqual(fields["zaa_enabled"]["kind"], "toggle")
        self.assertEqual(fields["zaa_min_z"]["enabled_when"],
                         {"key": "zaa_enabled", "not": "0"})
        changed = json.loads(apply_process_overrides(source, {
            "zaa_enabled": "1", "zaa_min_z": 0.12,
        }))
        self.assertEqual(changed["zaa_enabled"], "1")
        self.assertEqual(changed["zaa_min_z"], "0.12")


    def test_full_native_modes_cover_expert_and_multimaterial_sections(self):
        source = json.dumps({
            "name": "Orca process", "zaa_enabled": "0",
            "make_overhang_printable": "0", "fuzzy_skin": "none",
            "fuzzy_skin_thickness": "0.3", "enable_prime_tower": "0",
            "prime_tower_width": "35", "enable_support": "0",
            "support_type": "tree(auto)", "tree_support_tip_diameter": "0.8",
        }).encode()
        fields = process_schema(source)
        self.assertEqual(fields["zaa_enabled"]["level"], "expert")
        self.assertEqual(fields["fuzzy_skin"]["section"], "Fuzzy skin")
        self.assertEqual(fields["prime_tower_width"]["category"], "Multifilament")
        self.assertEqual(fields["prime_tower_width"]["enabled_when"],
                         {"key": "enable_prime_tower", "not": "0"})
        self.assertEqual(fields["tree_support_tip_diameter"]["enabled_when"],
                         [{"key": "enable_support", "not": "0"},
                          {"key": "support_type",
                           "in": ["tree(auto)", "tree(manual)"]}])
        edited = json.loads(apply_process_overrides(source, {
            "enable_prime_tower": "1", "prime_tower_width": 40,
            "fuzzy_skin": "external", "fuzzy_skin_thickness": 0.35,
        }))
        self.assertEqual(edited["prime_tower_width"], "40")
        self.assertEqual(edited["fuzzy_skin"], "external")
        self.assertEqual(edited["fuzzy_skin_thickness"], "0.35")

    def test_native_support_ironing_key_and_unsupported_key_rejection(self):
        source = json.dumps({"name": "Orca process", "support_ironing": "0",
                             "support_ironing_flow": "12%"}).encode()
        fields = process_schema(source)
        self.assertEqual(fields["support_ironing"]["kind"], "toggle")
        self.assertEqual(fields["support_ironing_flow"]["enabled_when"],
                         {"key": "support_ironing", "not": "0"})
        with self.assertRaises(ValueError):
            apply_process_overrides(source, {"enable_prime_tower": "1"})
        with self.assertRaises(ValueError):
            apply_process_overrides(source, {"machine_start_gcode": "M109"})

    def test_native_enum_and_toggle_settings_round_trip_without_touching_startup(self):
        source = json.dumps({
            "name": "Official sample", "sparse_infill_pattern": "grid",
            "seam_position": "aligned", "enable_support": "0",
            "outer_wall_acceleration": "2000",
            "machine_start_gcode": "START_PRINT EXTRUDER_TEMP=220",
            "change_filament_gcode": "M600",
        }).encode()
        schema = process_schema(source)
        self.assertEqual(schema["sparse_infill_pattern"]["current"], "grid")
        self.assertEqual(schema["enable_support"]["kind"], "toggle")
        edited = json.loads(apply_process_overrides(source, {
            "sparse_infill_pattern": "gyroid",
            "seam_position": "rear", "enable_support": "1",
            "outer_wall_acceleration": 2400,
        }))
        self.assertEqual(edited["sparse_infill_pattern"], "gyroid")
        self.assertEqual(edited["seam_position"], "rear")
        self.assertEqual(edited["enable_support"], "1")
        self.assertEqual(edited["outer_wall_acceleration"], "2400")
        self.assertEqual(edited["machine_start_gcode"], "START_PRINT EXTRUDER_TEMP=220")
        self.assertEqual(edited["change_filament_gcode"], "M600")

    def test_unrecognised_native_choices_are_not_replaced(self):
        source = json.dumps({"sparse_infill_pattern": "new-unknown-value"}).encode()
        self.assertNotIn("sparse_infill_pattern", process_schema(source))
        with self.assertRaises(ValueError):
            apply_process_overrides(source, {"sparse_infill_pattern": "gyroid"})

    def test_enum_and_toggle_values_are_strictly_whitelisted(self):
        for edits in (
            {"sparse_infill_pattern": "bogus"},
            {"sparse_infill_pattern": "G28"},
            {"seam_position": "not-present"},
            {"enable_support": True},
            {"enable_support": 1},
            {"enable_support": "yes"},
        ):
            with self.subTest(edits=edits), self.assertRaises(ValueError):
                validate_process_overrides(edits)

    def test_expert_metadata_matches_orca_grouping_and_basic_is_subset(self):
        profile = json.dumps({
            "layer_height": "0.2", "line_width": "0.42",
            "resolution": "0.012", "xy_hole_compensation": "0",
            "wall_loops": "2", "top_shell_thickness": "0.8",
            "sparse_infill_density": "15%", "sparse_infill_pattern": "grid",
            "default_acceleration": "12000", "outer_wall_speed": "200",
            "enable_support": "0", "support_top_z_distance": "0.2",
            "brim_width": "5", "brim_object_gap": "0.1",
        }).encode()
        fields = process_schema(profile)
        self.assertEqual(fields["layer_height"]["section"], "Layer height")
        self.assertEqual(fields["layer_height"]["level"], "basic")
        self.assertEqual(fields["resolution"]["section"], "Precision")
        self.assertEqual(fields["resolution"]["level"], "advanced")
        self.assertEqual(fields["top_shell_thickness"]["section"], "Top/bottom shells")
        self.assertEqual(fields["default_acceleration"]["section"], "Acceleration")
        self.assertEqual(fields["enable_support"]["section"], "Support")
        self.assertEqual(fields["brim_object_gap"]["section"], "Brim")
        self.assertEqual(fields["enable_support"]["level"], "basic")
        self.assertEqual(fields["brim_object_gap"]["level"], "advanced")
        self.assertEqual(fields["sparse_infill_pattern"]["section"], "Infill")

    def test_numeric_expert_settings_apply_to_temp_profile_only(self):
        source = json.dumps({
            "resolution": "0.012", "xy_hole_compensation": "0",
            "support_top_z_distance": "0.2", "brim_object_gap": "0.1",
            "machine_start_gcode": "START_PRINT",
        }).encode()
        updated = json.loads(apply_process_overrides(source, {
            "resolution": 0.025, "support_top_z_distance": 0.3,
            "brim_object_gap": 0.15,
        }))
        self.assertEqual(updated["resolution"], "0.025")
        self.assertEqual(updated["support_top_z_distance"], "0.3")
        self.assertEqual(updated["brim_object_gap"], "0.15")
        self.assertEqual(updated["xy_hole_compensation"], "0")
        self.assertEqual(updated["machine_start_gcode"], "START_PRINT")

    def test_mixed_unit_percentages_are_not_interpreted_as_distances(self):
        source = json.dumps({
            "line_width": "100%", "support_top_z_distance": "50%",
            "sparse_infill_density": "15%",
        }).encode()
        schema = process_schema(source)
        self.assertNotIn("line_width", schema)
        self.assertNotIn("support_top_z_distance", schema)
        self.assertEqual(schema["sparse_infill_density"]["current"], 15)
        edited = json.loads(apply_process_overrides(source, {
            "sparse_infill_density": 20,
        }))
        self.assertEqual(edited["sparse_infill_density"], "20%")

    def test_official_k2_style_profile_exposes_verified_expert_controls(self):
        # Representative native keys/values from OrcaSlicer v2.4.2:
        # resources/profiles/Creality/process/
        # 0.20mm Standard @Creality K2 0.4 nozzle.json
        source = json.dumps({
            "layer_height": "0.2", "wall_generator": "classic",
            "wall_loops": "2", "top_surface_pattern": "monotonicline",
            "bottom_surface_pattern": "monotonic",
            "sparse_infill_pattern": "grid", "infill_direction": "45",
            "infill_wall_overlap": "30%",
            "outer_wall_jerk": "8", "default_acceleration": "12000",
            "support_type": "normal(auto)", "enable_support": "0",
            "brim_object_gap": "0.1", "spiral_mode": "0",
            "top_solid_infill_flow_ratio": "1",
            "bottom_solid_infill_flow_ratio": "1",
            "print_sequence": "by layer",
            "filename_format": "{input_filename_base}.gcode",
        }).encode()
        schema = process_schema(source)
        for key in ("wall_generator", "top_surface_pattern", "bottom_surface_pattern",
                    "infill_direction", "outer_wall_jerk", "support_type",
                    "brim_object_gap", "spiral_mode", "top_solid_infill_flow_ratio"):
            self.assertIn(key, schema, key)
        self.assertIn("print_sequence", schema)
        self.assertEqual(schema["print_sequence"]["kind"], "choice")
        # User-provided filenames and G-code output templates are still protected.
        self.assertNotIn("filename_format", schema)
        edited = json.loads(apply_process_overrides(source, {
            "wall_generator": "arachne", "infill_direction": 30,
            "outer_wall_jerk": 9, "enable_support": "1",
        }))
        self.assertEqual(edited["wall_generator"], "arachne")
        self.assertEqual(edited["infill_direction"], "30")
        self.assertEqual(edited["outer_wall_jerk"], "9")
        self.assertEqual(edited["enable_support"], "1")
        self.assertEqual(edited["print_sequence"], "by layer")
        self.assertEqual(edited["filename_format"], "{input_filename_base}.gcode")

    def test_empty_overrides_leave_exact_original_bytes(self):
        source = self.sample()
        self.assertIs(apply_process_overrides(source, {}), source)
