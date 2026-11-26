import io
import zipfile
from unittest.mock import patch
from defusedxml import ElementTree as ET
from django.test import SimpleTestCase

from core.slicer_approval import fixture_stl
from core.slicer_streamed_plate_3mf import build_streamed_compound_3mf
from core.slicer_plate_3mf import NS
from core.slicer_profiles import SlicerProfileError


class StreamedFullPlateTests(SimpleTestCase):
    @patch("core.slicer_streamed_plate_3mf._available_bytes", return_value=8*1024**3)
    def test_twenty_distinct_sources_fit_one_compound_native_mesh(self, _memory):
        source = fixture_stl()
        models = []
        for i in range(20):
            raw = source.replace(b"10", str(11+i).encode("ascii"))
            models.append(({
                "x_mm": -80+(i%5)*40, "y_mm": -60+(i//5)*40,
                "rotation_deg": 0, "scale_percent": 100,
            }, raw))
        self.assertEqual(len(set(raw for _item, raw in models)), 20)
        project = build_streamed_compound_3mf(models, bed_width=220, bed_depth=220)
        with zipfile.ZipFile(io.BytesIO(project)) as archive:
            self.assertEqual(set(archive.namelist()),
                             {"3D/3dmodel.model","_rels/.rels","[Content_Types].xml"})
            root = ET.fromstring(archive.read("3D/3dmodel.model"))
        q = "{" + NS + "}"
        self.assertEqual(len(root.findall("./"+q+"resources/"+q+"object")), 1)
        self.assertEqual(len(root.findall("./"+q+"build/"+q+"item")), 1)
        vertices = root.findall(".//"+q+"vertex")
        triangles = root.findall(".//"+q+"triangle")
        self.assertEqual(len(triangles), 80)
        self.assertTrue(vertices)
        self.assertEqual(len({float(v.attrib["x"]) for v in vertices}) > 20, True)
        self.assertTrue(all(max(int(t.attrib[k]) for k in ("v1","v2","v3")) < len(vertices)
                            for t in triangles))

    @patch("core.slicer_streamed_plate_3mf._available_bytes", return_value=8*1024**3)
    def test_plain_models_only_no_silent_settings_loss(self, _memory):
        shape = fixture_stl()
        item = {"x_mm": -35, "y_mm": 0, "rotation_deg": 0,
                "scale_percent": 100, "process_overrides": {"wall_loops": 5}}
        with self.assertRaisesRegex(SlicerProfileError, "plain single-material"):
            build_streamed_compound_3mf([
                (item,shape), ({**item, "x_mm": 35},shape)
            ],bed_width=220,bed_depth=220)

    @patch("core.slicer_streamed_plate_3mf._available_bytes", return_value=256*1024**2)
    def test_memory_shortage_rejects_without_unbounded_xml_expansion(self, _memory):
        shape = fixture_stl()
        with self.assertRaisesRegex(SlicerProfileError,"available native slicing memory"):
            build_streamed_compound_3mf([
                ({"x_mm": -35,"y_mm":0,"rotation_deg":0,"scale_percent":100},shape),
                ({"x_mm": 35,"y_mm":0,"rotation_deg":0,"scale_percent":100},shape),
            ],bed_width=220,bed_depth=220)


    @patch("core.slicer_streamed_plate_3mf._available_bytes", return_value=8*1024**3)
    def test_repeated_source_rendered_once_with_independent_placements(self, _memory):
        from core.slicer_plate_3mf import _render_mesh
        shape = fixture_stl()
        item = {"x_mm": -35, "y_mm": 0, "rotation_deg": 0, "scale_percent": 100}
        with patch("core.slicer_streamed_plate_3mf._render_mesh", wraps=_render_mesh) as render:
            data = build_streamed_compound_3mf(
                [(item, shape), ({**item, "x_mm": 35}, shape)],
                bed_width=220, bed_depth=220)
        self.assertEqual(render.call_count, 1)
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            root = ET.fromstring(archive.read("3D/3dmodel.model"))
        q = "{" + NS + "}"
        vertices = root.findall(".//" + q + "vertex")
        faces = root.findall(".//" + q + "triangle")
        self.assertEqual(len(faces), 8)
        half = len(vertices) // 2
        self.assertGreater(half, 0)
        self.assertEqual(len(vertices), 2 * half)
        for first, second in zip(vertices[:half], vertices[half:]):
            self.assertAlmostEqual(float(second.attrib["x"]) - float(first.attrib["x"]), 70)
            self.assertEqual(first.attrib["y"], second.attrib["y"])
            self.assertEqual(first.attrib["z"], second.attrib["z"])

    @patch("core.slicer_streamed_plate_3mf._available_bytes", return_value=8*1024**3)
    def test_cached_source_still_checks_each_instance_placement(self, _memory):
        shape = fixture_stl()
        item = {"x_mm": 0, "y_mm": 0, "rotation_deg": 0, "scale_percent": 100}
        with self.assertRaisesRegex(SlicerProfileError, "Model 2 extends beyond"):
            build_streamed_compound_3mf(
                [(item, shape), ({**item, "x_mm": 200}, shape)],
                bed_width=220, bed_depth=220)
