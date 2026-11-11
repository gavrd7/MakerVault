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

    def test_lay_on_face_tilt_is_baked_and_sits_on_print_bed(self):
        source = fixture_stl()
        model = {"x_mm": 0, "y_mm": 0, "rotation_deg": 0,
                 "rotation_xyz_deg": [90, 0], "scale_percent": 100}
        data = build_plate_3mf([(model, source)], bed_width=220, bed_depth=220)
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            root = ET.fromstring(archive.read("3D/3dmodel.model"))
        ns = "{" + NS + "}"
        vertices = root.findall("./" + ns + "resources/" + ns + "object/" +
                                ns + "mesh/" + ns + "vertices/" + ns + "vertex")
        zs = [float(vertex.attrib["z"]) for vertex in vertices]
        self.assertTrue(zs)
        self.assertAlmostEqual(min(zs), 0, places=4)
        self.assertGreater(max(zs), 0)
        item = root.find("./" + ns + "build/" + ns + "item")
        self.assertEqual(item.attrib["transform"], "1 0 0 0 1 0 0 0 1 0 0 0")

    def test_untilted_geometry_retains_native_z_rotation(self):
        model = {"x_mm": 0, "y_mm": 0, "rotation_deg": 90,
                 "rotation_xyz_deg": [0, 0], "scale_percent": 100}
        data = build_plate_3mf([(model, fixture_stl())],
                                bed_width=220, bed_depth=220)
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            root = ET.fromstring(archive.read("3D/3dmodel.model"))
        item = root.find("./{%s}build/{%s}item" % (NS, NS))
        transform = [float(value) for value in item.attrib["transform"].split()]
        self.assertAlmostEqual(transform[0], 0, places=5)
        self.assertAlmostEqual(transform[1], 1, places=5)
        self.assertAlmostEqual(transform[3], -1, places=5)

    def test_object_settings_metadata_preserves_distinct_native_object_ids(self):
        shape = fixture_stl()
        identity = {"x_mm": 0, "y_mm": 0,
                    "rotation_deg": 0, "scale_percent": 100}
        models = [
            ({**identity, "x_mm": -35,
              "process_overrides": {"wall_loops": 5, "enable_support": "1"}}, shape),
            ({**identity, "x_mm": 35,
              "process_overrides": {"wall_loops": 2, "infill_wall_overlap": 18}}, shape),
        ]
        result = build_plate_3mf(models, bed_width=220, bed_depth=220)
        with zipfile.ZipFile(io.BytesIO(result)) as archive:
            model_xml = ET.fromstring(archive.read("3D/3dmodel.model"))
            config = ET.fromstring(archive.read("Metadata/model_settings.config"))
        self.assertEqual(len(model_xml.findall(".//{%s}object" % NS)), 2)
        objects = config.findall("object")
        self.assertEqual([obj.attrib["id"] for obj in objects], ["1", "2"])
        recorded = [{
            entry.attrib["key"]: entry.attrib["value"]
            for entry in obj.findall("metadata")
        } for obj in objects]
        self.assertEqual(recorded[0]["wall_loops"], "5")
        self.assertEqual(recorded[0]["enable_support"], "1")
        self.assertEqual(recorded[1]["wall_loops"], "2")
        self.assertAlmostEqual(float(recorded[1]["infill_wall_overlap"].removesuffix("%")), 18.0)
        self.assertEqual(len(config.find("plate").findall("model_instance")), 2)

    def test_individual_native_objects_have_baked_separated_placement(self):
        shape = fixture_stl()
        objects = [
            ({"x_mm": -35, "y_mm": 0, "rotation_deg": 0, "scale_percent": 100,
              "process_overrides": {"wall_loops": 2}}, shape),
            ({"x_mm": 35, "y_mm": 0, "rotation_deg": 0, "scale_percent": 100,
              "process_overrides": {"wall_loops": 5}}, shape),
        ]
        archive_bytes = build_plate_3mf(objects, bed_width=220, bed_depth=220)
        with zipfile.ZipFile(io.BytesIO(archive_bytes)) as package:
            root = ET.fromstring(package.read("3D/3dmodel.model"))
        ns = "{" + NS + "}"
        nodes = root.findall("./" + ns + "resources/" + ns + "object")
        self.assertEqual(len(nodes), 2)
        centers = []
        for obj in nodes:
            xs = [float(v.attrib["x"]) for v in
                  obj.findall("./" + ns + "mesh/" + ns + "vertices/" + ns + "vertex")]
            centers.append((min(xs) + max(xs)) / 2)
        self.assertAlmostEqual(centers[1] - centers[0], 70, places=3)
        placements = root.findall("./" + ns + "build/" + ns + "item")
        self.assertEqual(len(placements), 2)
        self.assertTrue(all(item.attrib["transform"] ==
                            "1 0 0 0 1 0 0 0 1 0 0 0"
                            for item in placements))

    def test_unsafe_object_settings_never_enter_native_3mf_metadata(self):
        shape = fixture_stl()
        instance = {"x_mm": 0, "y_mm": 0,
                    "rotation_deg": 0, "scale_percent": 100,
                    "process_overrides": {"machine_start_gcode": "M104 S300"}}
        with self.assertRaisesRegex(SlicerProfileError, "Invalid native per-object"):
            build_plate_3mf([(instance, shape)], bed_width=220, bed_depth=220)

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
