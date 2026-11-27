"""Prusa's exporter and isolated validator must agree on the exact project dialect."""
import io
import uuid
import zipfile
from unittest import TestCase
from xml.etree import ElementTree as ET
from defusedxml import ElementTree as SafeET

from core.slicer_prusa_3mf import build_prusa_native_3mf, validate_prusa_project_admission
from core.tests.test_slicer_prusa_plate import cube, item
from slicer_worker.prusa_3mf_validation import validate_prusa_native_3mf
from slicer_worker.runner import WorkerError

NS = "{http://schemas.microsoft.com/3dmanufacturing/core/2015/02}"


def volume(kind, settings=None):
    return {
        "id": str(uuid.uuid4()), "shape": "box", "kind": kind,
        "width_mm": 10, "depth_mm": 10, "height_mm": 18,
        "x_mm": 0, "y_mm": 0, "z_mm": 10,
        "coordinate_space": "world",
        "rotation_xyz_deg": [0, 0, 0],
        "scale_xyz_percent": [100, 100, 100],
        "settings": settings or {},
    }


def rewrite(archive, path, edit):
    src = io.BytesIO(archive)
    dst = io.BytesIO()
    with zipfile.ZipFile(src) as source, zipfile.ZipFile(dst, "w") as target:
        for part in source.namelist():
            data = source.read(part)
            if part == path:
                root = SafeET.fromstring(data)
                edit(root)
                data = ET.tostring(root)
            target.writestr(part, data)
    return dst.getvalue()


class PrusaProjectDialectTests(TestCase):
    def test_bare_and_independent_object_settings(self):
        raw = cube()
        for plate in (
            [(item(), raw)],
            [(item(x_mm=-35, process_overrides={"sparse_infill_density": 15}), raw),
             (item(x_mm=35, process_overrides={"sparse_infill_density": 60,
                                             "wall_loops": 4}), raw)],
        ):
            with self.subTest(objects=len(plate)):
                archive = build_prusa_native_3mf(plate, bed_width=250, bed_depth=210)
                receipt = validate_prusa_native_3mf(archive)
                self.assertEqual(receipt["objects"], len(plate))
                self.assertEqual(receipt["regions"], 0)

    def test_mixed_native_modifier_and_object_setting_are_serialized_independently(self):
        # Export is capable of the mixed dialect. Slice admission stays a
        # separate native qualification gate until the pinned CLI deposition
        # fixture proves both effects remain local to their own object.
        left = item(x_mm=-35, modifier_volumes=[
            {**volume("modifier", {"sparse_infill_density": 80}), "x_mm": -35}])
        right = item(x_mm=35, process_overrides={"sparse_infill_density": 80})
        archive = build_prusa_native_3mf([
            (left, cube()), (right, cube())],
            bed_width=250, bed_depth=210)
        # The qualified combination is independent: modifier on model one,
        # bounded object setting on model two. Same-model stacks and cavity
        # mixtures remain gated pending separate native proof.
        self.assertTrue(validate_prusa_project_admission(
            [left, right], {}, "2.9.7"))
        with self.assertRaisesRegex(ValueError, "share a modifier model"):
            validate_prusa_project_admission([
                {**left, "process_overrides": {"wall_loops": 4}}, right
            ], {}, "2.9.7")
        with self.assertRaisesRegex(ValueError, "negative cavities"):
            validate_prusa_project_admission([
                {**left, "modifier_volumes": [
                    {**volume("negative"), "x_mm": -35}
                ]}, right
            ], {}, "2.9.7")
        receipt = validate_prusa_native_3mf(archive)
        self.assertEqual(receipt["objects"], 2)
        self.assertEqual(receipt["regions"], 1)
        with zipfile.ZipFile(io.BytesIO(archive)) as package:
            metadata = SafeET.fromstring(package.read(
                "Metadata/Slic3r_PE_model.config"))
        objects = metadata.findall("object")
        self.assertEqual(len(objects), 2)
        self.assertTrue(any(entry.get("value") == "80%" for entry in
            objects[1].findall("metadata")))
        self.assertEqual(len(objects[0].findall("volume")), 2)
        self.assertEqual(len(objects[1].findall("volume")), 1)

    def test_qualified_modifier_and_negative_volumes_roundtrip(self):
        for kind, settings in (("modifier", {"sparse_infill_density": 80}),
                               ("negative", {})):
            with self.subTest(kind=kind):
                archive = build_prusa_native_3mf([
                    (item(modifier_volumes=[volume(kind, settings)]), cube())
                ], bed_width=250, bed_depth=210)
                receipt = validate_prusa_native_3mf(archive)
                self.assertEqual(receipt["regions"], 1)
                self.assertEqual(receipt["objects"], 1)

    def test_native_modifier_and_variable_z_metadata_can_coexist_before_slice_qualification(self):
        model = item(
            modifier_volumes=[volume("modifier", {"sparse_infill_density": 80})],
            variable_layer_profile={"version": 1, "bands": [
                {"from_mm": 4, "to_mm": 16, "layer_mm": .12},
            ]},
        )
        archive = build_prusa_native_3mf([(model, cube())],
                                          bed_width=250, bed_depth=210)
        receipt = validate_prusa_native_3mf(archive)
        self.assertEqual(receipt["objects"], 1)
        self.assertEqual(receipt["regions"], 1)
        self.assertGreaterEqual(receipt["layer_ranges"], 1)
        # This narrowly qualified combination is independently audited
        # against real pinned 2.9.7 G-code, not merely an importable 3MF.
        self.assertTrue(validate_prusa_project_admission(
            [model], {}, "2.9.7"))
        with self.assertRaisesRegex(ValueError, "combined native G-code proof"):
            validate_prusa_project_admission([
                {**model, "process_overrides": {"wall_loops": 4}}
            ], {}, "2.9.7")
        with self.assertRaisesRegex(ValueError, "combined native G-code proof"):
            validate_prusa_project_admission([
                {**model, "modifier_volumes": [
                    volume("negative")
                ]}
            ], {}, "2.9.7")
        with self.assertRaisesRegex(ValueError, "combined native G-code proof"):
            validate_prusa_project_admission([
                model, item(x_mm=45)
            ], {}, "2.9.7")

    def test_all_shared_primitive_region_meshes_remain_native_prusa_volumes(self):
        from core.slicer_modifier_volumes import PRIMITIVE_SHAPES
        for shape in sorted(PRIMITIVE_SHAPES):
            with self.subTest(shape=shape):
                modifier = {**volume("modifier", {"wall_loops": 4}),
                            "shape": shape}
                project = build_prusa_native_3mf([
                    (item(modifier_volumes=[modifier]), cube())
                ], bed_width=250, bed_depth=210)
                check = validate_prusa_native_3mf(project)
                self.assertEqual(check["objects"], 1)
                self.assertEqual(check["regions"], 1)
                self.assertGreater(check["triangles"], 12)

    def test_native_prusa_support_seam_and_fuzzy_annotations_roundtrip(self):
        from core.slicer_plate_3mf import _triangles
        from core.slicer_native_support_paint import _fingerprint
        raw = cube()
        faces = list(_triangles(raw))
        local = [[(v[0]-10, v[1]-10, v[2]) for v in face] for face in faces]
        face = local[0]
        centre = [sum(point[i] for point in face)/3 for i in range(3)]
        patch = [[(point[i]+centre[i])/2 for i in range(3)] for point in face]
        def paint(slot):
            return {"version": 2, "signature": _fingerprint(local),
                    "regions": [{"slot": slot,
                                 "patches": [{"face": 0, "polygon": patch}]}]}
        model = item(support_paint=paint(0), seam_paint=paint(1),
                     fuzzy_skin_paint=paint(0))
        archive = build_prusa_native_3mf([(model, raw)], bed_width=250, bed_depth=210)
        audit = validate_prusa_native_3mf(archive)
        self.assertEqual(len(audit["paint_channels"]), 3)
        with zipfile.ZipFile(io.BytesIO(archive)) as package:
            source = SafeET.fromstring(package.read("3D/3dmodel.model"))
        faces = source.findall(f"./{NS}resources/{NS}object/{NS}mesh/{NS}triangles/{NS}triangle")
        prusa = "{http://schemas.slic3r.org/3mf/2017/06}"
        self.assertTrue(any(f.get(prusa+"custom_supports") == "4" and
                            f.get(prusa+"custom_seam") == "8" and
                            f.get(prusa+"fuzzy_skin") == "4" for f in faces))
        self.assertGreater(len(faces), 12)
        def tamper(root):
            face = next(node for node in root.findall(
                f"./{NS}resources/{NS}object/{NS}mesh/{NS}triangles/{NS}triangle")
                if prusa+"custom_supports" in node.attrib)
            face.set(prusa+"custom_supports", "FFFF")
        with self.assertRaises(WorkerError):
            validate_prusa_native_3mf(rewrite(archive, "3D/3dmodel.model", tamper))


    def test_three_object_support_paint_admission_retains_one_exact_enforcer(self):
        from scripts.prusa_generate_support_overhang import cantilever, support_mask
        raw = cantilever()
        for painted in range(3):
            with self.subTest(painted=painted):
                plate = [
                    item(x_mm=x, **({"support_paint":support_mask(raw, 0)}
                                    if i==painted else {}))
                    for i,x in enumerate((-68,0,68))]
                self.assertFalse(
                    validate_prusa_project_admission(plate, {}, "2.9.7"))
                archive = build_prusa_native_3mf(
                    [(model,raw) for model in plate],
                    bed_width=250,bed_depth=210)
                receipt = validate_prusa_native_3mf(archive)
                self.assertEqual(receipt["objects"],3)
                self.assertIn(
                    "slic3rpe:FdmSupportsPaintingVersion",
                    receipt["paint_channels"])
                other = dict(plate[(painted+1)%3])
                other["process_overrides"] = {"wall_loops":4}
                plate[(painted+1)%3] = other
                with self.assertRaises(ValueError):
                    validate_prusa_project_admission(plate, {}, "2.9.7")

    def test_two_object_support_enforcer_roundtrips_but_mixed_edits_fail_closed(self):
        from scripts.prusa_generate_support_overhang import cantilever, support_mask
        model = cantilever()
        paint = support_mask(model, 0)
        for painted_index in (0, 1):
            with self.subTest(painted_index=painted_index):
                rows = [
                    item(x_mm=-50, **({"support_paint": paint} if painted_index == 0 else {})),
                    item(x_mm=50, **({"support_paint": paint} if painted_index == 1 else {})),
                ]
                self.assertFalse(validate_prusa_project_admission(rows, {}, "2.9.7"))
                archive = build_prusa_native_3mf(
                    [(row, model) for row in rows], bed_width=250, bed_depth=210)
                receipt = validate_prusa_native_3mf(archive)
                self.assertEqual(receipt["objects"], 2)
                self.assertIn("slic3rpe:FdmSupportsPaintingVersion",
                              receipt["paint_channels"])
                with zipfile.ZipFile(io.BytesIO(archive)) as package:
                    tree = SafeET.fromstring(package.read("3D/3dmodel.model"))
                namespace = "{http://schemas.slic3r.org/3mf/2017/06}"
                objects = tree.findall(f"./{NS}resources/{NS}object")
                marked = [any(face.get(namespace+"custom_supports") == "4"
                              for face in obj.findall(f"./{NS}mesh/{NS}triangles/{NS}triangle"))
                          for obj in objects]
                self.assertEqual(marked, [i == painted_index for i in (0, 1)])
                for changed in ({"rotation_deg": 45},
                                {"process_overrides": {"wall_loops": 3}},
                                {"fuzzy_skin_paint": {"regions": [{"slot": 0}]}}):
                    other = 1-painted_index
                    invalid = list(rows)
                    invalid[other] = {**invalid[other], **changed}
                    with self.assertRaises(ValueError):
                        validate_prusa_project_admission(invalid, {}, "2.9.7")
                with self.assertRaises(ValueError):
                    validate_prusa_project_admission([
                        {**rows[0], "support_paint": paint},
                        {**rows[1], "support_paint": paint},
                    ], {}, "2.9.7")

    def test_two_independent_objects_each_keep_a_typed_region(self):
        for kind, overrides in (("modifier", {"sparse_infill_density": 80}),
                                ("negative", {})):
            with self.subTest(kind=kind):
                left = {**volume(kind, overrides), "x_mm": -35}
                right = {**volume(kind, overrides), "x_mm": 35}
                project = build_prusa_native_3mf([
                    (item(x_mm=-35, modifier_volumes=[left]), cube()),
                    (item(x_mm=35, modifier_volumes=[right]), cube()),
                ], bed_width=250, bed_depth=210)
                receipt = validate_prusa_native_3mf(project)
                self.assertEqual(receipt["objects"], 2)
                self.assertEqual(receipt["regions"], 2)

    def test_independent_two_object_paint_channels_validate_without_cross_talk(self):
        from core.slicer_plate_3mf import _triangles
        from core.slicer_native_support_paint import _fingerprint
        raw = cube()
        faces = list(_triangles(raw))
        local = [[(v[0]-10, v[1]-10, v[2]) for v in face]
                 for face in faces]
        patch = {"version": 2, "signature": _fingerprint(local),
                 "regions": [{"slot": 0, "patches": [{
                     "face": 0,
                     "polygon": [list(p) for p in local[0]],
                 }]}]}
        for field in ("support_paint", "fuzzy_skin_paint"):
            for index in (0, 1):
                with self.subTest(field=field, index=index):
                    rows = [(item(x_mm=-35), raw),(item(x_mm=35), raw)]
                    row = {**rows[index][0], field: patch}
                    rows[index] = (row, raw)
                    project = build_prusa_native_3mf(rows,
                        bed_width=250,bed_depth=210)
                    receipt = validate_prusa_native_3mf(project)
                    self.assertEqual(receipt["objects"], 2)
                    self.assertEqual(len(receipt["paint_channels"]), 1)
                    self.assertEqual(receipt["regions"], 0)

    def test_native_prusa_layer_ranges_roundtrip_and_reject_tampering(self):
        plate = [(item(variable_layer_profile={"version": 1, "bands": [
            {"from_mm": 4, "to_mm": 16, "layer_mm": .12}]}), cube())]
        raw = build_prusa_native_3mf(plate, bed_width=250, bed_depth=210)
        self.assertEqual(validate_prusa_native_3mf(raw)["layer_ranges"], 1)
        part = "Metadata/Prusa_Slicer_layer_config_ranges.xml"
        def mutate(root):
            root.find("./object/range/option").set("opt_key", "post_process")
        with self.assertRaises(WorkerError):
            validate_prusa_native_3mf(rewrite(raw, part, mutate))
        def bad_id(root):
            root.find("./object").set("id", "12")
        with self.assertRaises(WorkerError):
            validate_prusa_native_3mf(rewrite(raw, part, bad_id))
        def overlap(root):
            element = root.find("./object")
            interval = ET.SubElement(element, "range", {"min_z": "6", "max_z": "18"})
            ET.SubElement(interval, "option", {"opt_key": "layer_height"}).text = ".13"
        with self.assertRaises(WorkerError):
            validate_prusa_native_3mf(rewrite(raw, part, overlap))

    def test_worker_rejects_script_and_unknown_volume_metadata(self):
        raw = build_prusa_native_3mf([
            (item(modifier_volumes=[volume("modifier", {"wall_loops": 6})]), cube())
        ], bed_width=250, bed_depth=210)
        path = "Metadata/Slic3r_PE_model.config"
        def inject(root):
            ET.SubElement(root.find("./object/volume"), "metadata", {
                "type": "volume", "key": "post_process", "value": "untrusted"})
        with self.assertRaises(WorkerError):
            validate_prusa_native_3mf(rewrite(raw, path, inject))
        def invalid_role(root):
            root.find("./object/volume[2]/metadata").set("value", "ModelPart")
        with self.assertRaises(WorkerError):
            validate_prusa_native_3mf(rewrite(raw, path, invalid_role))

    def test_worker_rejects_malformed_triangle_ranges_and_offbed_source(self):
        raw = build_prusa_native_3mf([(item(), cube())], bed_width=250, bed_depth=210)
        def corrupt(root):
            root.find(f"./{NS}resources/{NS}object/{NS}mesh/{NS}triangles/{NS}triangle").set("v1", "999999")
        with self.assertRaises(WorkerError):
            validate_prusa_native_3mf(rewrite(raw, "3D/3dmodel.model", corrupt))
