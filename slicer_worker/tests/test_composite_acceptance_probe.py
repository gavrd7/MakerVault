"""Regression checks for exact-binary composite G-code evidence.

These tests do not approve any engine for production. They verify that the
diagnostic accounts for real positive-E moves and records feature attribution.
"""
import unittest

from slicer_worker.composite_acceptance_probe import two_model_region_extrusion


class CompositeNativeEvidenceTests(unittest.TestCase):
    def test_extrusion_is_attributed_to_both_independent_printables(self):
        code = b"\n".join([
            b"G90", b"M83", b"G0 X85 Y105 Z15",
            b"; FEATURE: Internal infill",
            b"G1 X95 Y105 E1.50",
            b"G1 X100 Y105 E0.50",
            b"G0 X125 Y105",
            b"; FEATURE: Outer wall",
            b"G1 X135 Y105 E2.25",
            b"; FEATURE: Support",
            b"G1 X140 Y105 E0.75",
        ])
        evidence = two_model_region_extrusion(code)
        self.assertEqual(evidence["counts"], {"left": 2, "right": 2})
        self.assertAlmostEqual(evidence["totals"]["left"], 2.0)
        self.assertAlmostEqual(evidence["totals"]["right"], 3.0)
        self.assertAlmostEqual(evidence["features"]["left"]["Internal infill"], 2.0)
        self.assertAlmostEqual(evidence["features"]["right"]["Outer wall"], 2.25)
        self.assertAlmostEqual(evidence["features"]["right"]["Support"], 0.75)

    def test_retraction_travel_and_out_of_band_do_not_prove_model_effects(self):
        code = b"\n".join([
            b"G90", b"M83", b"G0 X85 Y105 Z15",
            b"G1 X95 Y105 E-1",
            b"G0 X100 Y105",
            b"G1 X110 Y105 E2",
            b"G0 X125 Y105 Z25",
            b"G1 X135 Y105 E3",
            b"G0 X125 Y105 Z15",
            b"G1 X135 Y105 E1",
        ])
        evidence = two_model_region_extrusion(code)
        self.assertEqual(evidence["counts"], {"left": 0, "right": 1})
        self.assertAlmostEqual(evidence["totals"]["right"], 1.0)

    def test_absolute_extrusion_reset_only_counts_positive_e(self):
        code = b"\n".join([
            b"G90", b"M82", b"G92 E0",
            b"G0 X85 Y105 Z15",
            b"G1 X95 Y105 E1.5",
            b"G1 X100 Y105 E1",
            b"G92 E0",
            b"G1 X95 Y105 E0.75",
        ])
        evidence = two_model_region_extrusion(code)
        self.assertEqual(evidence["counts"]["left"], 2)
        self.assertAlmostEqual(evidence["totals"]["left"], 2.25)


if __name__ == "__main__":
    unittest.main()
