"""Prusa's exporter and isolated validator must agree on the exact project dialect."""
import io
import uuid
import zipfile
from unittest import TestCase
from xml.etree import ElementTree as ET
from defusedxml import ElementTree as SafeET

from core.slicer_prusa_3mf import build_prusa_native_3mf
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
