"""Single-material Prusa plate geometry is baked without 3MF or object settings."""
import math
import struct
from unittest import TestCase

from core.slicer_prusa_plate import build_prusa_placed_stl
from core.slicer_profiles import SlicerProfileError
from core.slicer_mesh import inspect_stl


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


class PrusaPlacedStlTests(TestCase):
    def test_two_independent_models_preserve_visual_xy_placement(self):
        baked = build_prusa_placed_stl([
            (item(x_mm=-35),cube()), (item(x_mm=35),cube()),
        ], bed_width=220, bed_depth=220)
        self.assertEqual(inspect_stl(baked)["triangles"],24)
        first = [v[0] for v in vertices(baked)[:36]]
        second = [v[0] for v in vertices(baked)[36:]]
        self.assertAlmostEqual(min(first),65,places=3)
        self.assertAlmostEqual(max(first),85,places=3)
        self.assertAlmostEqual(min(second),135,places=3)
        self.assertAlmostEqual(max(second),155,places=3)

    def test_scale_rotation_and_z_floor_are_baked(self):
        baked = build_prusa_placed_stl([
            (item(scale_xyz_percent=[200,50,100], rotation_deg=90), cube()),
        ], bed_width=220, bed_depth=220)
        coords = vertices(baked)
        self.assertAlmostEqual(max(v[0] for v in coords)-min(v[0] for v in coords),10,places=3)
        self.assertAlmostEqual(max(v[1] for v in coords)-min(v[1] for v in coords),40,places=3)
        self.assertAlmostEqual(min(v[2] for v in coords),0,places=3)

    def test_x_axis_rotation_preserves_bed_contact(self):
        baked = build_prusa_placed_stl([
            (item(rotation_xyz_deg=[90,0]),cube()),
        ], bed_width=220, bed_depth=220)
        self.assertAlmostEqual(min(v[2] for v in vertices(baked)),0,places=3)

    def test_unverified_objects_and_offbed_models_rejected(self):
        for bad in (
            item(x_mm=200), item(z_mm=10), item(process_overrides={"wall_loops":4}),
            item(modifier_volumes=[{"kind":"negative"}]),
            item(colour_paint={"regions":[{"colour":"red"}]}),
            item(variable_layer_profile={"bands":[{"z":2}]}),
        ):
            with self.subTest(bad=bad):
                with self.assertRaises(SlicerProfileError):
                    build_prusa_placed_stl([(bad,cube())],bed_width=220,bed_depth=220)
