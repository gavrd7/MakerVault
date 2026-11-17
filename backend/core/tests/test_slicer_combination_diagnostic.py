"""The combination diagnostic must never mutate or silently keep paint masks."""
import copy
from django.test import SimpleTestCase

from core.management.commands.diagnose_slicer_combination import (
    CASES, FEATURES, selected_variant,
)


class OfflineCombinedPaintDiagnosticTests(SimpleTestCase):
    def test_progressive_masks_do_not_alter_saved_draft(self):
        original = {
            "asset_id": "source", "instance_id": "model",
            "fuzzy_skin_paint": {"regions": [{"slot": 0}]},
            "seam_paint": {"regions": [{"slot": 1}]},
            "support_paint": {"regions": [{"slot": 0}]},
            "variable_layer_profile": {"bands": [
                {"from_mm": 5, "to_mm": 10, "layer_mm": 0.12}]},
        }
        saved = copy.deepcopy(original)
        expected = (
            set(),
            {"variable_layer_profile"},
            {"fuzzy_skin_paint"},
            {"fuzzy_skin_paint", "variable_layer_profile"},
            {"fuzzy_skin_paint", "seam_paint"},
            {"fuzzy_skin_paint", "seam_paint", "variable_layer_profile"},
            {"fuzzy_skin_paint", "seam_paint", "support_paint"},
            set(FEATURES),
        )
        self.assertEqual(len(CASES), len(expected))
        for (_, enabled), wanted in zip(CASES, expected):
            variant = selected_variant(original, enabled)
            self.assertEqual(set(variant) & set(FEATURES), wanted)
            self.assertEqual(variant["asset_id"], "source")
        self.assertEqual(original, saved)

    def test_plain_3mf_baseline_cannot_carry_hidden_paint_channels(self):
        source = {"asset_id": "source", "fuzzy_skin_paint": {"regions": [1]},
                  "seam_paint": {"regions": [1]}, "support_paint": {"regions": [1]},
                  "variable_layer_profile": {"bands": [1]}}
        baseline = selected_variant(source, ())
        self.assertEqual(baseline, {"asset_id": "source"})
