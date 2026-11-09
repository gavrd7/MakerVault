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

    def test_empty_overrides_leave_exact_original_bytes(self):
        source = self.sample()
        self.assertIs(apply_process_overrides(source, {}), source)
