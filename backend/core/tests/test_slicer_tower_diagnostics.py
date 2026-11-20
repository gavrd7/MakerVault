"""Safety-focused offline G-code tower deposition measurements."""
from django.test import SimpleTestCase

from core.slicer_tower_diagnostics import tower_deposition_metrics


class TowerDepositionTests(SimpleTestCase):
    def test_absolute_xy_and_e_with_native_feature_switching(self):
        gcode = (
            b"G90\nM82\nG1 X15 Y25 E0\n"
            b";TYPE:Outer wall\nG1 X20 Y25 E1\n"
            b";TYPE:Wipe tower\nG1 X50 Y60 E2\n"
            b"G1 X60 Y60 E3\nG1 X60 Y70 E4\n"
            b";TYPE:Outer wall\nG1 X100 Y100 E5\n"
        )
        result = tower_deposition_metrics(gcode)
        self.assertEqual(result["classification"], "native_feature_marker")
        # Tower's first extrusion starts at prior XY (20,25).
        self.assertEqual(result["xy_width_mm"], 40.0)
        self.assertEqual(result["xy_depth_mm"], 45.0)
        self.assertEqual(result["positive_e_length_mm"], 3.0)
        self.assertEqual(result["deposition_moves"], 3)
        self.assertEqual(result["tower_feature_markers"], 1)

    def test_relative_e_and_g92_resets_dont_count_retractions(self):
        gcode = (
            b"G90\nM83\nG1 X10 Y10\n; FEATURE: Prime tower\n"
            b"G1 X20 Y10 E.5\nG1 X30 Y10 E-.3\n"
            b"G92 E0\nG1 X30 Y20 E.25\n"
        )
        result = tower_deposition_metrics(gcode)
        self.assertEqual(result["deposition_moves"], 2)
        self.assertEqual(result["positive_e_length_mm"], 0.75)
        self.assertEqual(result["xy_width_mm"], 20.0)
        self.assertEqual(result["xy_depth_mm"], 10.0)

    def test_no_explicit_tower_marker_fails_closed(self):
        result = tower_deposition_metrics(
            b"G90\nM82\nG1 X20 Y20 E1\nG1 X30 Y30 E2\n")
        self.assertEqual(result["classification"], "unavailable_no_verified_tower_moves")
        self.assertIsNone(result["xy_width_mm"])
        self.assertIsNone(result["xy_depth_mm"])
        self.assertIsNone(result["positive_e_length_mm"])

    def test_tower_marker_without_positive_extrusion_is_not_measured(self):
        result = tower_deposition_metrics(
            b";TYPE:Wipe tower\nG1 X20 Y20\nG1 X30 Y30 E-1\n")
        self.assertEqual(result["classification"], "unavailable_no_verified_tower_moves")
        self.assertEqual(result["tower_feature_markers"], 1)

    def test_untrusted_coordinates_rejected(self):
        with self.assertRaises(ValueError):
            tower_deposition_metrics(b";TYPE:Prime tower\nG1 Xinf Y10 E1\nG1 X999999 Y20 E2\n")
