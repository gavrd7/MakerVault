"""Creality single-material plate geometry must preserve per-model transforms."""
from django.test import SimpleTestCase

from core.slicer_creality_plate import build_creality_single_filament_plate
from core.slicer_mesh import inspect_stl
from core.tests.test_slicer_prusa_plate import cube, item, vertices
from core.slicer_profiles import SlicerProfileError


class CrealityPlainPlateTests(SimpleTestCase):
    def test_three_distinct_models_keep_explicit_bed_coordinates(self):
        models = [
            (item(x_mm=-40, y_mm=-30), cube(size=10)),
            (item(x_mm=0, y_mm=25, rotation_deg=90), cube(size=12)),
            (item(x_mm=40, y_mm=-15), cube(size=14)),
        ]
        output = build_creality_single_filament_plate(
            models, bed_width=260, bed_depth=260)
        self.assertEqual(inspect_stl(output)["triangles"], 36)
        coords = vertices(output)
        expected = ((90, 100), (130, 155), (170, 115))
        for index, (x, y) in enumerate(expected):
            with self.subTest(model=index):
                part = coords[index * 36:(index + 1) * 36]
                self.assertAlmostEqual(
                    (min(p[0] for p in part) + max(p[0] for p in part)) / 2,
                    x)
                self.assertAlmostEqual(
                    (min(p[1] for p in part) + max(p[1] for p in part)) / 2,
                    y)

    def test_creality_plate_still_rejects_bed_overflow(self):
        with self.assertRaisesRegex(SlicerProfileError, "beyond the native build plate"):
            build_creality_single_filament_plate(
                [(item(x_mm=200), cube(size=20))],
                bed_width=260, bed_depth=260)

    def test_creality_byte_budget_cannot_exceed_worker_transport(self):
        from unittest.mock import patch
        from core import slicer_prusa_plate as encoder
        with patch.object(encoder, "MAX_STL_BYTES", 8 * 1024 * 1024):
            data = build_creality_single_filament_plate(
                [(item(), cube(size=10))], bed_width=260, bed_depth=260)
        self.assertLessEqual(len(data), 32 * 1024 * 1024)
