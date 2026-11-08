import json
from django.test import SimpleTestCase

from core.slicer_profile_edit import customise_native_json
from core.slicer_profiles import SlicerProfileError


class NativeSlicerProfileEditorTests(SimpleTestCase):
    def test_customised_orca_process_preserves_unrelated_native_fields(self):
        original = json.dumps({
            "name": "Original process", "layer_height": "0.20",
            "wall_loops": "2", "sparse_infill_pattern": "gyroid",
            "sparse_infill_density": "15%",
        }).encode()
        copy = customise_native_json(original, "process", "My process", {
            "layer_height": 0.16, "wall_loops": 3, "sparse_infill_density": 25,
        })
        edited = json.loads(copy)
        self.assertEqual(edited["name"], "My process")
        self.assertEqual(edited["layer_height"], "0.16")
        self.assertEqual(edited["wall_loops"], "3")
        self.assertEqual(edited["sparse_infill_density"], "25%")
        self.assertEqual(edited["sparse_infill_pattern"], "gyroid")
        self.assertEqual(json.loads(original)["layer_height"], "0.20")

    def test_creality_native_filament_list_shape_preserved(self):
        original = json.dumps({
            "name": "Creality PETG", "nozzle_temperature": ["245"],
            "hot_plate_temp": ["80"],
        }).encode()
        edited = json.loads(customise_native_json(original, "filament", "My PETG", {
            "nozzle_temperature": 250,
        }))
        self.assertEqual(edited["nozzle_temperature"], ["250"])
        self.assertEqual(edited["hot_plate_temp"], ["80"])

    def test_k2_long_retraction_must_be_explicitly_adjusted_on_a_copy(self):
        original = json.dumps({
            "name": "Official Creality K2 0.4 nozzle",
            "retraction_distances_when_cut": "30",
            "nozzle_diameter": ["0.4"],
        }).encode()
        candidate = json.loads(customise_native_json(
            original, "printer", "K2 CLI compatibility candidate",
            {"retraction_distances_when_cut": 18},
        ))
        self.assertEqual(candidate["retraction_distances_when_cut"], "18")
        self.assertEqual(candidate["nozzle_diameter"], ["0.4"])
        self.assertEqual(json.loads(original)["retraction_distances_when_cut"], "30")
        with self.assertRaises(SlicerProfileError):
            customise_native_json(
                original, "printer", "Invalid K2 value",
                {"retraction_distances_when_cut": 30},
            )

    def test_unsafe_keys_numeric_ranges_and_postprocessors_are_rejected(self):
        original = b'{"name":"Original","layer_height":"0.2"}'
        for edits in (
            {"post_process": 1}, {"layer_height": 100},
            {"layer_height": float("nan")}, {"wall_loops": 1.5},
        ):
            with self.subTest(edits=edits), self.assertRaises(SlicerProfileError):
                customise_native_json(original, "process", "Custom", edits)
        with self.assertRaises(SlicerProfileError):
            customise_native_json(b'{"post_process":"evil"}', "process", "Custom",
                                  {"layer_height": 0.2})
