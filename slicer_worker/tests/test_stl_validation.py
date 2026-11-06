import math
import struct
from unittest import TestCase

from slicer_worker.stl_validation import StlValidationError, validate_stl


def binary_triangle(values=None):
    values = values or (0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 10.0, 0.0, 0.0, 0.0, 10.0, 0.0)
    return b"Binary STL".ljust(80, b" ") + struct.pack("<I", 1) + struct.pack("<12fH", *values, 0)


ASCII_TRIANGLE = b"""solid part
facet normal 0 0 1
 outer loop
  vertex 0 0 0
  vertex 10 0 0
  vertex 0 10 0
 endloop
endfacet
endsolid part
"""


class StlValidationTests(TestCase):
    def test_valid_binary_and_ascii_stl(self):
        self.assertEqual(validate_stl(binary_triangle())["triangles"], 1)
        self.assertEqual(validate_stl(binary_triangle())["format"], "binary")
        self.assertEqual(validate_stl(ASCII_TRIANGLE)["format"], "ascii")

    def test_incomplete_binary_and_invalid_mesh_are_rejected(self):
        for raw in (
            b"", b"stl", binary_triangle()[:-1], b"not-a-mesh",
            binary_triangle((0, 0, math.inf, 0, 0, 0, 1, 0, 0, 0, 1, 0)),
            ASCII_TRIANGLE.replace(b"vertex 0 10 0", b"vertex inf 0 0"),
        ):
            with self.subTest(raw=raw[:25]), self.assertRaises(StlValidationError):
                validate_stl(raw)

    def test_ascii_stl_rejects_misordered_and_unclosed_facets(self):
        for raw in (
            ASCII_TRIANGLE.replace(b"outer loop", b"endloop", 1),
            ASCII_TRIANGLE.replace(b"endfacet", b""),
            ASCII_TRIANGLE.replace(b"endsolid part", b""),
            ASCII_TRIANGLE.replace(b"vertex 0 10 0", b""),
            ASCII_TRIANGLE.replace(b"facet normal 0 0 1", b"facet normal inf 0 1"),
            ASCII_TRIANGLE + b"facet normal 0 0 1\\n",
            b"solid empty\\nendsolid empty\\n",
        ):
            with self.subTest(raw=raw[:80]), self.assertRaises(StlValidationError):
                validate_stl(raw)

    def test_committed_small_tetrahedron_fixture(self):
        from pathlib import Path
        fixture_path = Path(__file__).parents[1] / "fixtures" / "tetrahedron.stl"
        report = validate_stl(fixture_path.read_bytes())
        self.assertEqual(report, {"format": "ascii", "triangles": 4})

    def test_triangle_count_cap(self):
        data = b"header".ljust(80, b" ") + struct.pack("<I", 500_001)
        with self.assertRaises(StlValidationError):
            validate_stl(data)
