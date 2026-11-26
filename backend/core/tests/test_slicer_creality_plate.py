"""Creality single-material plate geometry must preserve per-model transforms."""
from django.test import SimpleTestCase

from core.slicer_creality_plate import build_creality_single_filament_plate
from core.slicer_mesh import inspect_stl
import math
import struct
def cube(size=20):
    # A closed 12-triangle binary cube matching the worker's STL conventions.
    p = [(0,0,0),(size,0,0),(size,size,0),(0,size,0),
         (0,0,size),(size,0,size),(size,size,size),(0,size,size)]
    faces = [(0,2,1),(0,3,2),(4,5,6),(4,6,7),
             (0,1,5),(0,5,4),(1,2,6),(1,6,5),
             (2,3,7),(2,7,6),(3,0,4),(3,4,7)]
    data = bytearray(b"Prusa acceptance cube".ljust(80,b"\0") + struct.pack("<I",len(faces)))
    for a,b,c in faces:
        data.extend(struct.pack("<12fH", 0.,0.,0.,*p[a],*p[b],*p[c],0))
    return bytes(data)


def item(**kwargs):
    return {
        "asset_id": "owned",
        "x_mm": 0, "y_mm": 0, "z_mm": 0,
        "rotation_deg": 0, "rotation_xyz_deg": [0,0],
        "scale_percent": 100, "scale_xyz_percent": [100,100,100],
        **kwargs,
    }


def vertices(raw):
    return [v for tri in struct.iter_unpack("<12fH", raw[84:])
            for v in (tri[3:6],tri[6:9],tri[9:12])]



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

    def test_creality_plate_uses_shared_resource_budget(self):
        from unittest.mock import patch
        from core import slicer_placed_stl as encoder
        with patch.object(encoder, "input_model_budget", return_value=4096):
            data = build_creality_single_filament_plate(
                [(item(), cube(size=10))], bed_width=260, bed_depth=260)
        self.assertLessEqual(len(data), 4096)

    def test_twenty_distinct_source_models_preserve_native_stl_facet_count(self):
        models = [(item(x_mm=-80 + (i % 5) * 40,
                        y_mm=-60 + (i // 5) * 40),
                   cube(size=8 + i % 5)) for i in range(20)]
        output = build_creality_single_filament_plate(
            models, bed_width=260, bed_depth=260)
        self.assertEqual(inspect_stl(output)["triangles"], 20 * 12)
