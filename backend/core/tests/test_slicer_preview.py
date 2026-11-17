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

    def test_native_arc_extrusion_is_rendered_as_curved_path_not_chord(self):
        import math
        result=generated_preview(
            "G90\\nM83\\nG1 X10 Y0 Z0.2\\n"
            ";TYPE:Outer wall\\nG3 X0 Y10 I-10 J0 E1\\n"
        )
        self.assertGreater(result["segment_count"], 20)
        self.assertFalse(result["sampled"])
        self.assertEqual(result["layers"],[0.2])
        path=result["segments"]
        self.assertEqual(path[0][:2],[10.0,0.0])
        self.assertEqual(path[-1][2:4],[0.0,10.0])
        self.assertTrue(all(abs(math.hypot(point[2],point[3])-10)<0.01
                            for point in path))
        self.assertEqual(result["feature_counts"]["Outer wall"],len(path))

    def test_radius_format_arc_and_absolute_arc_centres(self):
        radius=generated_preview(
            "G90\\nM83\\nG1 X10 Y0 Z0.2\\n"
            "G3 X0 Y10 R10 E1\\n"
        )
        self.assertGreater(len(radius["segments"]),20)
        absolute=generated_preview(
            "G90\\nG90.1\\nM83\\nG1 X10 Y0 Z0.2\\n"
            "G3 X0 Y10 I0 J0 E1\\n"
        )
        self.assertGreater(len(absolute["segments"]),20)
        self.assertEqual(radius["unresolved_arc_moves"],0)
        self.assertEqual(absolute["unresolved_arc_moves"],0)

    def test_non_extruding_arcs_do_not_create_false_bridges(self):
        result=generated_preview(
            "G90\\nM83\\nG1 X10 Y0 Z0.2\\n"
            "G3 X0 Y10 I-10 J0\\n"
            "G1 X0 Y15 E1\\n"
        )
        self.assertEqual(result["segment_count"],1)
        self.assertEqual(result["segments"][0][:4],[0.0,10.0,0.0,15.0])

    def test_malformed_arc_never_creates_straight_extrusion_chord(self):
        result=generated_preview(
            "G90\\nM83\\nG1 X10 Y0 Z0.2\\n"
            "G2 X30 Y10 R1 E1\\n"
            "G1 X32 Y10 E1\\n"
        )
        self.assertEqual(result["segment_count"],1)
        self.assertEqual(result["segments"][0][:4],[30.0,10.0,32.0,10.0])

    def test_truncated_scan_never_claims_complete_layer_count(self):
        result = generated_preview("G1 X2 Y3 E1\n", truncated=True)
        self.assertIsNone(result["layer_count"])
        self.assertTrue(result["sampled"])
