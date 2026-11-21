"""The combination diagnostic must never mutate or silently keep paint masks."""
import copy
from django.test import SimpleTestCase

from core.management.commands.diagnose_slicer_combination import (
    CASES, FEATURES, selected_variant, range_probe_variants,
    layer_thickness_probe_variants,
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

    def test_range_relocation_preserves_original_band_and_settings(self):
        original = {"variable_layer_profile": {"version": 1, "bands": [
            {"from_mm": 36.5, "to_mm": 46.5, "layer_mm": .12}
        ]}}
        before = copy.deepcopy(original)
        variants = range_probe_variants(original)
        self.assertEqual(len(variants), 4)
        self.assertEqual([label for label, _ in variants],
                         ["range-at-5mm", "range-at-12mm",
                          "range-at-22mm", "range-at-32mm"])
        for label, bands in variants:
            self.assertEqual(len(bands), 1)
            self.assertAlmostEqual(bands[0]["to_mm"] - bands[0]["from_mm"], 10)
            self.assertEqual(bands[0]["layer_mm"], .12)
        self.assertEqual(original, before)

    def test_range_probes_decline_ambiguous_multi_band_draft(self):
        self.assertEqual(range_probe_variants({"variable_layer_profile":
            {"bands": [{"from_mm": 1, "to_mm": 3, "layer_mm": .12},
                       {"from_mm": 4, "to_mm": 6, "layer_mm": .12}]}}), ())

    def test_layer_height_probes_do_not_change_saved_draft(self):
        saved = {"variable_layer_profile": {"version": 1, "bands": [
            {"from_mm": 36.5, "to_mm": 46.5, "layer_mm": 0.12}]}}
        original = copy.deepcopy(saved)
        variants = layer_thickness_probe_variants(saved)
        self.assertEqual([name for name, _ in variants],
                         ["layer-height-0.16mm", "layer-height-0.20mm",
                          "layer-height-0.24mm"])
        self.assertEqual([bands[0]["layer_mm"] for _, bands in variants],
                         [0.16, 0.20, 0.24])
        for _, bands in variants:
            self.assertEqual((bands[0]["from_mm"], bands[0]["to_mm"]), (36.5, 46.5))
        self.assertEqual(saved, original)
