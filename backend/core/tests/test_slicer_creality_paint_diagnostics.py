"""Offline Creality feature diagnostic invariants (no engine required)."""
from django.test import SimpleTestCase

from core.management.commands.diagnose_creality_paint_features import (
    _metrics, _patch_for_model,
)
from core.slicer_approval import fixture_stl


class CrealityPaintingDiagnosticTests(SimpleTestCase):
    def test_generated_patch_is_bounded_and_fingerprinted(self):
        signature, face, polygon, height = _patch_for_model(fixture_stl())
        self.assertIn(":", signature)
        self.assertGreaterEqual(face, 0)
        self.assertEqual(len(polygon), 3)
        self.assertGreater(height, 3)
        self.assertTrue(all(len(point) == 3 for point in polygon))

    def test_motion_compare_does_not_count_changed_header_as_toolpath(self):
        first = _metrics(b"; generated: 1\n;Z:0.2\nT0\nG1 X1 Y1 E0.1\n")
        second = _metrics(b"; generated: 2\n;Z:0.2\nT0\nG1 X1 Y1 E0.1\n")
        third = _metrics(b"; generated: 2\n;Z:0.2\nT0\nG1 X1 Y1 E0.3\n")
        self.assertNotEqual(first["gcode_sha256"], second["gcode_sha256"])
        self.assertEqual(first["motion_sha256"], second["motion_sha256"])
        self.assertNotEqual(first["motion_sha256"], third["motion_sha256"])
        self.assertEqual(first["tool0_selects"], 1)
        self.assertEqual(first["g1_with_extrusion"], 1)
