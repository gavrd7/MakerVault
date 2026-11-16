from django.test import SimpleTestCase
from core.slicer_semantic_painting import validate_semantic_paint
from core.slicer_variable_layers import validate_variable_layer_profile


class SemanticPaintTests(SimpleTestCase):
    def setUp(self):
        self.patch = {"face": 0, "polygon": [[0, 0, 0], [2, 0, 0], [0, 2, 0]]}
        self.region = {"version": 2, "signature": "2:abcdef01",
                       "regions": [{"slot": 0, "patches": [self.patch]}]}

    def test_seam_enforcer_and_blocker_preserve_separate_meanings(self):
        self.assertEqual(validate_semantic_paint(self.region, "seam"), self.region)
        block = {**self.region, "regions": [{"slot": 1, "patches": [self.patch]}]}
        self.assertEqual(validate_semantic_paint(block, "seam"), block)
        with self.assertRaises(ValueError):
            validate_semantic_paint(block, "fuzzy")

    def test_fuzzy_skin_only_accepts_painted_mask_state(self):
        self.assertEqual(validate_semantic_paint(self.region, "fuzzy"), self.region)
        for invalid in (
            {**self.region, "palette": []},
            {**self.region, "version": 1},
            {**self.region, "regions": [{"slot": 3, "patches": [self.patch]}]},
        ):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                validate_semantic_paint(invalid, "fuzzy")


class VariableLayerDraftTests(SimpleTestCase):
    def test_valid_bands_are_normalised_and_sorted(self):
        value = {"version": 1, "bands": [
            {"from_mm": 20, "to_mm": 30, "layer_mm": 0.12},
            {"from_mm": 0, "to_mm": 20, "layer_mm": 0.2},
        ]}
        result = validate_variable_layer_profile(value)
        self.assertEqual([b["from_mm"] for b in result["bands"]], [0, 20])

    def test_bad_layers_and_overlaps_are_rejected(self):
        for bands in (
            [{"from_mm": 0, "to_mm": 20, "layer_mm": 0.01}],
            [{"from_mm": 5, "to_mm": 5, "layer_mm": 0.2}],
            [{"from_mm": 0, "to_mm": 10, "layer_mm": 0.12},
             {"from_mm": 9, "to_mm": 15, "layer_mm": 0.2}],
        ):
            with self.subTest(bands=bands), self.assertRaises(ValueError):
                validate_variable_layer_profile({"version": 1, "bands": bands})
