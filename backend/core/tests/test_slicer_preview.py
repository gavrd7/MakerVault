from django.test import SimpleTestCase
from core.slicer_preview import generated_preview


class SlicerPreviewTests(SimpleTestCase):
    def test_extracts_native_duration_filament_and_extrusion_features(self):
        raw = """; estimated printing time (normal mode) = 1h 20m 30s
; filament used [mm] = 1520.0
; filament used [g] = 4.8
; filament used [cm3] = 3.9
G90
M82
G1 X10 Y10 Z0.2 F1200
;TYPE:Outer wall
G1 X20 Y10 E0.6
G1 X20 Y20 E1.2
G1 Z0.4
;TYPE:Sparse infill
G1 X10 Y20 E2.0
"""
        result = generated_preview(raw)
        self.assertEqual(result["estimated_time_seconds"], 4830)
        self.assertEqual(result["filament_mm"], 1520.0)
        self.assertEqual(result["filament_g"], 4.8)
        self.assertEqual(result["filament_cm3"], 3.9)
        self.assertEqual(result["layers"], [0.2, 0.4])
        self.assertEqual(result["layer_count"], 2)
        self.assertEqual(result["segment_count"], 3)
        self.assertEqual(result["feature_counts"]["Outer wall"], 2)

    def test_native_line_width_is_preserved_for_3d_filament_geometry(self):
        result = generated_preview(
            "G90\nM83\nG1 Z0.2 X10 Y10\n"
            ";WIDTH:0.46\n;TYPE:Outer wall\nG1 X20 E1.0\n"
            ";WIDTH:999\nG1 X30 E1.0\n"
        )
        self.assertEqual(len(result["segments"]), 2)
        self.assertEqual(result["segments"][0][6], 0.46)
        self.assertEqual(result["segments"][1][6], 0.46)
        self.assertEqual(result["feature_counts"]["Outer wall"], 2)

    def test_dense_preview_budget_is_bounded(self):
        from core.slicer_preview import MAX_SEGMENTS
        self.assertGreater(MAX_SEGMENTS, 6000)
        self.assertLessEqual(MAX_SEGMENTS, 100000)

    def test_missing_metadata_is_unknown_not_guessed(self):
        result = generated_preview("G1 X2 Y3 E1\n")
        self.assertIsNone(result["estimated_time_seconds"])
        self.assertIsNone(result["filament_g"])

    def test_relative_extrusion_and_g92_reset(self):
        result = generated_preview(
            "M83\nG1 Z0.2\nG1 X10 E1\nG1 X20 E0.5\nG92 E0\nG1 X30 E1\n"
        )
        self.assertEqual(result["segment_count"], 3)

    def test_truncated_scan_never_claims_complete_layer_count(self):
        result = generated_preview("G1 X2 Y3 E1\n", truncated=True)
        self.assertIsNone(result["layer_count"])
        self.assertTrue(result["sampled"])
