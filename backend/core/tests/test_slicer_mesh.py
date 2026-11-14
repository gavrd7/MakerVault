import struct
from django.test import SimpleTestCase
from core.slicer_mesh import inspect_stl, MeshInspectionError


ASCII = b"""solid part
facet normal 0 0 1
outer loop
vertex -5 0 0
vertex 5 0 0
vertex 0 10 2
endloop
endfacet
endsolid part
"""


class SlicerMeshInspectionTests(SimpleTestCase):
    def test_ascii_mesh_bounds_report_source_coordinates_not_plate_fit(self):
        result = inspect_stl(ASCII)
        self.assertEqual(result["size_mm"], [10, 10, 2])
        self.assertEqual(result["bounds_mm"]["min"], [-5, 0, 0])
        self.assertEqual(result["printer_fit"], "not_checked")

    def test_binary_mesh_dimensions(self):
        raw = b"binary".ljust(80, b" ") + struct.pack("<I", 1) + struct.pack(
            "<12fH", 0, 0, 1, 0, 0, 0, 30, 0, 0, 0, 50, 6, 0,
        )
        result = inspect_stl(raw)
        self.assertEqual(result["size_mm"], [30, 50, 6])
        self.assertEqual(result["triangles"], 1)

    def test_malformed_and_truncated_input_is_rejected(self):
        for data in (b"", b"garbage", ASCII.replace(b"endfacet", b""),
                     ASCII.replace(b"endsolid part", b""),
                     ASCII.replace(b"vertex 0 10 2", b"vertex NaN 10 2")):
            with self.subTest(data=data[:35]), self.assertRaises(MeshInspectionError):
                inspect_stl(data)
