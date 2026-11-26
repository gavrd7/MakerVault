import io
import zipfile
from unittest.mock import patch
from defusedxml import ElementTree as ET
from django.test import SimpleTestCase

from core.slicer_approval import fixture_stl
from core.slicer_compact_plate_3mf import compact_repeated_plate
from core.slicer_plate_3mf import NS


class CompactRepeatedPlateTests(SimpleTestCase):
    def test_twenty_instances_share_single_mesh_and_keep_exact_placements(self):
        raw = fixture_stl()
        rows = [
            ({"x_mm": -80 + i % 5 * 40, "y_mm": -60 + i // 5 * 40,
              "rotation_deg": 0, "scale_percent": 100}, raw)
            for i in range(20)
        ]
        data = compact_repeated_plate(rows, bed_width=220, bed_depth=220)
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            root = ET.fromstring(archive.read("3D/3dmodel.model"))
            self.assertEqual(len(archive.namelist()), 3)
        q = "{" + NS + "}"
        self.assertEqual(len(root.findall("./"+q+"resources/"+q+"object")), 2)
        self.assertEqual(len(root.findall(".//"+q+"mesh")), 1)
        components = root.findall(".//"+q+"component")
        self.assertEqual(len(components), 20)
        self.assertEqual(len({c.attrib["transform"] for c in components}), 20)
        self.assertTrue(all(c.attrib["objectid"] == "1" for c in components))

    def test_distinct_stls_fall_back_to_original_builder(self):
        raw = fixture_stl()
        rows = [
            ({"x_mm": -35, "y_mm": 0, "rotation_deg": 0, "scale_percent": 100}, raw),
            ({"x_mm": 35, "y_mm": 0, "rotation_deg": 0, "scale_percent": 100},
             raw.replace(b"10", b"11")),
        ]
        self.assertIsNone(compact_repeated_plate(rows, bed_width=220, bed_depth=220))

    def test_instance_specific_settings_disable_compact_route(self):
        raw = fixture_stl()
        item = {"x_mm": -35, "y_mm": 0, "rotation_deg": 0,
                "scale_percent": 100, "process_overrides": {"wall_loops": 4}}
        self.assertIsNone(compact_repeated_plate([
            (item, raw), ({**item, "x_mm": 35}, raw)
        ], bed_width=220, bed_depth=220))

    def test_compact_plate_does_not_repeat_stl_mesh_serialization(self):
        from core import slicer_plate_3mf as plate
        original = plate._render_mesh
        calls = []
        def track(*args, **kwargs):
            calls.append(1)
            return original(*args, **kwargs)
        raw = fixture_stl()
        rows = [
            ({"x_mm": -80 + i % 5 * 40, "y_mm": -60 + i // 5 * 40,
              "rotation_deg": 0, "scale_percent": 100}, raw)
            for i in range(20)
        ]
        with patch.object(plate, "_render_mesh", side_effect=track):
            compact_repeated_plate(rows, bed_width=220, bed_depth=220)
        self.assertEqual(len(calls), 1)
