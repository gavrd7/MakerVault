import io
import zipfile
from defusedxml import ElementTree as ET
from django.test import SimpleTestCase
from core.slicer_approval import fixture_stl
from core.slicer_plate_3mf import build_plate_3mf, build_compound_plate_3mf, NS
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
                "Metadata/model_settings.config",
            })
            root = ET.fromstring(archive.read("3D/3dmodel.model"))
            plate_manifest = ET.fromstring(archive.read("Metadata/model_settings.config"))
        self.assertEqual(plate_manifest.tag, "config")
        self.assertEqual(len(plate_manifest.find("plate").findall("model_instance")), 2)
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

    def test_single_material_compound_keeps_both_printable_islands(self):
        source = fixture_stl()
        items = [
            ({"x_mm": -35, "y_mm": 0, "rotation_deg": 0, "scale_percent": 100}, source),
            ({"x_mm": 35, "y_mm": 0, "rotation_deg": 90, "scale_percent": 100}, source),
        ]
        data = build_compound_plate_3mf(items, bed_width=220, bed_depth=220)
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            self.assertEqual(set(archive.namelist()), {
                "3D/3dmodel.model", "[Content_Types].xml", "_rels/.rels",
            })
            root = ET.fromstring(archive.read("3D/3dmodel.model"))
        objects = root.findall(".//{%s}object" % NS)
        builds = root.findall(".//{%s}build/{%s}item" % (NS, NS))
        self.assertEqual(len(objects), 1)
        self.assertEqual(len(builds), 1)
        self.assertEqual(len(objects[0].findall(".//{%s}triangle" % NS)), 8)
        values = [float(v.attrib["x"]) for v in objects[0].findall(".//{%s}vertex" % NS)]
        self.assertGreater(max(values) - min(values), 60)

    def test_compound_rejects_bed_overflow_and_malformed_sources(self):
        shape = fixture_stl()
        model = {"x_mm": 0, "y_mm": 0, "rotation_deg": 0, "scale_percent": 100}
        with self.assertRaises(SlicerProfileError):
            build_compound_plate_3mf([(model, shape), ({**model, "x_mm": 150}, shape)],
                                     bed_width=220, bed_depth=220)
        with self.assertRaises(SlicerProfileError):
            build_compound_plate_3mf([(model, shape), (model, b"bad STL")],
                                     bed_width=220, bed_depth=220)

    def test_independent_xyz_scale_is_encoded_in_single_and_compound_plates(self):
        shape = fixture_stl()
        item = {
            "x_mm": 0, "y_mm": 0, "rotation_deg": 90,
            "scale_percent": 100, "scale_xyz_percent": [150, 50, 200],
        }
        data = build_plate_3mf([(item, shape)], bed_width=220, bed_depth=220)
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            root = ET.fromstring(archive.read("3D/3dmodel.model"))
        build = root.find(".//{%s}build/{%s}item" % (NS, NS))
        matrix = [float(value) for value in build.attrib["transform"].split()]
        self.assertAlmostEqual(matrix[1], 1.5, places=5)
        self.assertAlmostEqual(matrix[3], -0.5, places=5)
        self.assertAlmostEqual(matrix[8], 2.0, places=5)
        composite = build_compound_plate_3mf([
            ({**item, "x_mm": -35}, shape),
            ({**item, "x_mm": 35}, shape),
        ], bed_width=220, bed_depth=220)
        with zipfile.ZipFile(io.BytesIO(composite)) as archive:
            root = ET.fromstring(archive.read("3D/3dmodel.model"))
        vertices = root.findall(".//{%s}vertex" % NS)
        self.assertGreater(len(vertices), 0)

    def test_invalid_individual_scale_fails_at_3mf_boundary(self):
        item = {"x_mm": 0, "y_mm": 0, "rotation_deg": 0, "scale_percent": 100}
        for xyz in ([0, 100, 100], [101, 401, 100], [100, float("nan"), 100],
                    [100, True, 100], [100, 100]):
            with self.subTest(xyz=xyz), self.assertRaises(SlicerProfileError):
                build_plate_3mf([({**item, "scale_xyz_percent": xyz}, fixture_stl())],
                                bed_width=220, bed_depth=220)

    def test_missing_bed_and_invalid_mesh_fail_closed(self):
        item = {"x_mm": 0, "y_mm": 0, "rotation_deg": 0, "scale_percent": 100}
        with self.assertRaises(SlicerProfileError):
            build_plate_3mf([(item, fixture_stl())], bed_width=0, bed_depth=220)
        with self.assertRaises(SlicerProfileError):
            build_plate_3mf([(item, b"not an STL")], bed_width=220, bed_depth=220)
