import io
import zipfile
from defusedxml import ElementTree as ET
from django.test import SimpleTestCase
from core.slicer_approval import fixture_stl
from core.slicer_plate_3mf import build_plate_3mf, NS
from core.slicer_profiles import SlicerProfileError


class BuildPlate3MFTests(SimpleTestCase):
    def test_multiple_meshes_preserve_distinct_transforms(self):
        shape = fixture_stl()
        items = [
            ({"x_mm": 0, "y_mm": 0, "rotation_deg": 0, "scale_percent": 100}, shape),
            ({"x_mm": 20, "y_mm": -10, "rotation_deg": 90, "scale_percent": 50}, shape),
        ]
        data = build_plate_3mf(items, bed_width=220, bed_depth=220)
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            self.assertEqual(set(archive.namelist()), {
                "3D/3dmodel.model", "[Content_Types].xml", "_rels/.rels",
            })
            root = ET.fromstring(archive.read("3D/3dmodel.model"))
        objects = root.findall(".//{%s}object" % NS)
        build = root.findall(".//{%s}build/{%s}item" % (NS, NS))
        self.assertEqual(len(objects), 2)
        self.assertEqual(len(build), 2)
        for obj in objects:
            self.assertEqual(len(obj.findall(".//{%s}triangle" % NS)), 4)
        first = list(map(float, build[0].attrib["transform"].split()))
        second = list(map(float, build[1].attrib["transform"].split()))
        self.assertEqual(len(first), 12)
        self.assertEqual((first[9], first[10]), (110, 110))
        self.assertEqual((second[9], second[10]), (130, 100))
        self.assertAlmostEqual(second[1], 0.5, places=5)
        self.assertAlmostEqual(second[3], -0.5, places=5)

    def test_missing_bed_and_invalid_mesh_fail_closed(self):
        item = {"x_mm": 0, "y_mm": 0, "rotation_deg": 0, "scale_percent": 100}
        with self.assertRaises(SlicerProfileError):
            build_plate_3mf([(item, fixture_stl())], bed_width=0, bed_depth=220)
        with self.assertRaises(SlicerProfileError):
            build_plate_3mf([(item, b"not an STL")], bed_width=220, bed_depth=220)
