import io
import json
import uuid
import zipfile
from defusedxml import ElementTree as ET
from django.test import SimpleTestCase
from core.slicer_approval import fixture_stl
from core.slicer_plate_3mf import build_plate_3mf, build_compound_plate_3mf, build_makervault_project_3mf, NS
from core.slicer_profiles import SlicerProfileError


class MultiPlateProject3MFTests(SimpleTestCase):
    def test_export_keeps_separate_plates_and_native_meshes(self):
        model = fixture_stl()
        obj = {"asset_id": str(uuid.uuid4()), "x_mm": 12, "y_mm": -4, "rotation_deg": 45,
               "scale_percent": 90, "color": "#cc33aa",
               "process_overrides": {"wall_loops": 3}}
        metadata = {
            "format": "makervault-project-v1",
            "active_plate_id": "plate-1",
            "plates": [
                {"id": "plate-1", "name": "First",
                 "objects": [{**obj, "instance_id": "one"}]},
                {"id": "plate-2", "name": "Second",
                 "objects": [{**obj, "instance_id": "two"}]},
            ],
            "filament": {"preset": "PLA", "spool_id": "spool1"},
            "process": {"overrides": {"wall_loops": 3}},
        }
        data=build_makervault_project_3mf([
            ("First", [(obj,model)]),
            ("Second", [(obj,model)]),
        ],bed_width=220,bed_depth=220,metadata=metadata)
        with zipfile.ZipFile(io.BytesIO(data)) as package:
            contents=set(package.namelist())
            self.assertIn("Metadata/plates/plate-1.3mf",contents)
            self.assertIn("Metadata/plates/plate-2.3mf",contents)
            self.assertEqual(json.loads(package.read(
                "Metadata/makervault-project.json")),metadata)
            root=ET.fromstring(package.read("3D/3dmodel.model"))
            config=ET.fromstring(package.read("Metadata/model_settings.config"))
        self.assertEqual(len(root.findall(".//{%s}object" % NS)),2)
        self.assertEqual(len(root.findall(".//{%s}build/{%s}item" % (NS,NS))),2)
        self.assertEqual(len(config.findall("plate")),2)
        plate_ids=[[x.attrib["value"] for x in node.findall("metadata")
                    if x.attrib["key"]=="plater_id"]
                   for node in config.findall("plate")]
        self.assertEqual(plate_ids,[["1"],["2"]])


    def test_v2_paint_regions_are_exported_into_exact_project_sidecars(self):
        shape = fixture_stl()
        asset_id = str(uuid.uuid4())
        paint = {"version": 2, "signature": "1:abcdef01",
                 "palette": [{"color": "#ff0000", "label": "Red"}],
                 "regions": [{"slot": 0, "patches": [
                     {"face": 0, "polygon": [[0, 0, 0], [2, 0, 0], [0, 2, 0]]}
                 ]}]}
        item = {"asset_id": asset_id, "instance_id": str(uuid.uuid4()),
                "x_mm": 0, "y_mm": 0, "rotation_deg": 0,
                "scale_percent": 100, "color": "#123456", "colour_paint": paint}
        metadata = {"format": "makervault-project-v1", "active_plate_id": "plate-1",
                    "plates": [{"id": "plate-1", "name": "Plate 1", "objects": [item]}]}
        data = build_makervault_project_3mf(
            [("Plate 1", [(item, shape)])], bed_width=220, bed_depth=220,
            metadata=metadata)
        with zipfile.ZipFile(io.BytesIO(data)) as package:
            exported = json.loads(package.read("Metadata/makervault-project.json"))
            stored_item = exported["plates"][0]["objects"][0]
            self.assertNotIn("colour_paint", stored_item)
            self.assertEqual(stored_item["paint_sidecar"],
                             "Metadata/paint/paint-0001.json")
            self.assertEqual(json.loads(package.read(stored_item["paint_sidecar"])), paint)
            self.assertEqual(metadata["plates"][0]["objects"][0]["colour_paint"], paint)

    def test_semantic_paint_sidecars_and_variable_bands_survive_export(self):
        shape = fixture_stl()
        patch = {"face": 0, "polygon": [[0, 0, 0], [2, 0, 0], [0, 2, 0]]}
        paint = {"version": 2, "signature": "1:abcdef01",
                 "regions": [{"slot": 0, "patches": [patch]}]}
        variable = {"version": 1, "bands": [
            {"from_mm": 0, "to_mm": 10, "layer_mm": 0.12}
        ]}
        item = {"asset_id": str(uuid.uuid4()), "instance_id": str(uuid.uuid4()),
                "x_mm": 0, "y_mm": 0, "rotation_deg": 0, "scale_percent": 100,
                "color": "#123456", "seam_paint": paint,
                "fuzzy_skin_paint": paint, "variable_layer_profile": variable}
        metadata = {"format": "makervault-project-v1", "active_plate_id": "plate-1",
                    "plates": [{"id": "plate-1", "name": "Plate 1", "objects": [item]}]}
        data = build_makervault_project_3mf(
            [("Plate 1", [(item, shape)])], bed_width=220, bed_depth=220,
            metadata=metadata)
        with zipfile.ZipFile(io.BytesIO(data)) as package:
            exported = json.loads(package.read("Metadata/makervault-project.json"))
            saved = exported["plates"][0]["objects"][0]
            for field, prefix in (("seam_paint", "seam"), ("fuzzy_skin_paint", "fuzzy")):
                self.assertNotIn(field, saved)
                self.assertEqual(json.loads(package.read(saved[prefix + "_sidecar"])), paint)
            self.assertEqual(saved["variable_layer_profile"], variable)
            self.assertEqual(item["seam_paint"], paint)
            self.assertEqual(item["fuzzy_skin_paint"], paint)


class BuildPlate3MFTests(SimpleTestCase):
    def test_elevation_is_preserved_in_individual_and_compound_3mf(self):
        shape = fixture_stl()
        items = [
            ({"x_mm": -25, "y_mm": 0, "z_mm": 0,
              "rotation_deg": 0, "scale_percent": 100}, shape),
            ({"x_mm": 25, "y_mm": 0, "z_mm": 12.5,
              "rotation_deg": 0, "scale_percent": 100}, shape),
        ]
        for builder in (build_plate_3mf, build_compound_plate_3mf):
            data = builder(items, bed_width=220, bed_depth=220)
            with zipfile.ZipFile(io.BytesIO(data)) as archive:
                root = ET.fromstring(archive.read("3D/3dmodel.model"))
            ns = "{" + NS + "}"
            if builder is build_plate_3mf:
                objects = root.findall("./" + ns + "resources/" + ns + "object")
                placements = root.findall("./" + ns + "build/" + ns + "item")
                self.assertEqual(len(objects), 2)
                # Native Orca consumes transforms baked into resource
                # vertices, while the build-item matrices stay identity.
                second = [float(v) for v in placements[1].attrib["transform"].split()]
                self.assertAlmostEqual(second[11], 0, places=3)
                second_vertices = objects[1].findall(
                    "./" + ns + "mesh/" + ns + "vertices/" + ns + "vertex")
                self.assertTrue(second_vertices)
                self.assertAlmostEqual(min(float(v.attrib["z"]) for v in
                                           second_vertices), 12.5, places=3)
            else:
                vertices = root.findall(".//" + ns + "vertex")
                zs = sorted({round(float(v.attrib["z"]), 3) for v in vertices})
                self.assertTrue(any(z >= 12.5 for z in zs))

    def test_tilted_elevated_mesh_preserves_requested_bottom_height(self):
        shape = fixture_stl()
        item = {"x_mm": 0, "y_mm": 0, "z_mm": 8.5,
                "rotation_deg": 0, "rotation_xyz_deg": [90, 0],
                "scale_percent": 100}
        data = build_plate_3mf([(item, shape)], bed_width=220, bed_depth=220)
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            root = ET.fromstring(archive.read("3D/3dmodel.model"))
        zs = [float(v.attrib["z"]) for v in root.findall(".//{%s}vertex" % NS)]
        self.assertAlmostEqual(min(zs), 8.5, places=3)

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

    def test_native_support_paint_subdivides_facets_without_changing_mesh_area(self):
        from core.slicer_plate_3mf import _triangles
        from core.slicer_native_support_paint import _fingerprint
        shape = fixture_stl()
        source = list(_triangles(shape))
        extent_min = [min(p[a] for tri in source for p in tri) for a in range(3)]
        extent_max = [max(p[a] for tri in source for p in tri) for a in range(3)]
        center = [(extent_min[0]+extent_max[0])/2,
                  (extent_min[1]+extent_max[1])/2, extent_min[2]]
        local = [[tuple(p[a]-center[a] for a in range(3)) for p in tri]
                 for tri in source]
        face = local[0]
        centroid = [sum(p[a] for p in face)/3 for a in range(3)]
        patch = [[(p[a]+centroid[a])/2 for a in range(3)] for p in face]
        obj = {
            "x_mm": 0, "y_mm": 0, "rotation_deg": 0,
            "rotation_xyz_deg": [0,0], "scale_percent": 100,
            "support_paint": {"version": 2, "signature": _fingerprint(local),
                              "regions": [{"slot": 0, "patches": [
                                  {"face": 0, "polygon": patch}]}]},
        }
        archive_bytes = build_plate_3mf([(obj,shape)],bed_width=220,bed_depth=220)
        with zipfile.ZipFile(io.BytesIO(archive_bytes)) as archive:
            mesh = ET.fromstring(archive.read("3D/3dmodel.model"))
            triangles = mesh.findall(".//{%s}triangle" % NS)
            native = ET.fromstring(archive.read("Metadata/model_settings.config"))
        self.assertGreater(len(triangles),len(source))
        self.assertTrue(any(face.attrib.get("paint_supports")=="4" for face in triangles))
        self.assertTrue(any("paint_supports" not in face.attrib for face in triangles))
        self.assertEqual(len(native.find("plate").findall("model_instance")),1)

    def test_variable_layer_ranges_are_native_orca_3mf_per_object(self):
        base = {"x_mm": 0, "y_mm": 0, "rotation_deg": 0,
                "scale_percent": 100, "rotation_xyz_deg": [0, 0]}
        model = fixture_stl()
        plate = [
            ({**base, "x_mm": -20}, model),
            ({**base, "x_mm": 20, "variable_layer_profile": {"version": 1,
                "bands": [{"from_mm": 1, "to_mm": 3, "layer_mm": .12},
                          {"from_mm": 3, "to_mm": 5, "layer_mm": .16}]}}, model),
        ]
        result = build_plate_3mf(plate, bed_width=220, bed_depth=220)
        with zipfile.ZipFile(io.BytesIO(result)) as archive:
            ranges = ET.fromstring(archive.read("Metadata/layer_config_ranges.xml"))
            native = ET.fromstring(archive.read("3D/3dmodel.model"))
            self.assertIn("Metadata/model_settings.config", archive.namelist())
        self.assertEqual([item.attrib["id"] for item in ranges.findall("object")], ["2"])
        bands = ranges.findall("./object/range")
        self.assertEqual([(b.attrib["min_z"], b.attrib["max_z"]) for b in bands],
                         [("1.000", "3.000"), ("3.000", "5.000")])
        self.assertEqual([b.find("option").attrib["opt_key"] for b in bands],
                         ["layer_height", "layer_height"])
        self.assertEqual([b.find("option").text for b in bands], ["0.120", "0.160"])
        self.assertEqual(len(native.findall(".//{%s}object" % NS)), 2)

    def test_variable_layer_range_export_rejects_tilt_and_scaling(self):
        shape = fixture_stl()
        base = {"x_mm": 0, "y_mm": 0, "rotation_deg": 0,
                "scale_percent": 100,
                "variable_layer_profile": {"version": 1, "bands": [
                    {"from_mm": 0, "to_mm": 10, "layer_mm": .12}]}}
        for change in ({"rotation_xyz_deg": [90, 0]},
                       {"z_mm": 3}, {"scale_percent": 90}):
            with self.subTest(change=change):
                with self.assertRaisesRegex(SlicerProfileError, "Variable layer"):
                    build_plate_3mf([({**base, **change}, shape)],
                                     bed_width=220, bed_depth=220)

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
