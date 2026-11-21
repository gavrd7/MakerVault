"""Creality 7.3.1 3MF project transport contract tests."""
import io
import json
import zipfile
from unittest import TestCase
from unittest.mock import patch

from slicer_worker.creality_project_validation import validate_creality_project
from slicer_worker.runner import WorkerError


class NativeCreality3MFContractTests(TestCase):
    def project(self, *, project=None, identity=True):
        config = {"name": "project_settings", "from": "project",
                  "version": "7.3.1",
                  "filament_settings_id": ["grey", "yellow"]}
        config.update(project or {})
        data = io.BytesIO()
        with zipfile.ZipFile(data, "w", compression=zipfile.ZIP_DEFLATED) as z:
            z.writestr("3D/3dmodel.model",
                '<?xml version="1.0" encoding="UTF-8"?>'
                '<model xmlns="http://schemas.microsoft.com/3dmanufacturing/core/2015/02" '
                'unit="millimeter"><metadata name="Application">'
                'Creality_Print V7.3.1</metadata><resources>'
                '<object id="1"/><object id="2"/></resources><build/></model>')
            z.writestr("Metadata/model_settings.config",
                       '<config><object id="1"><metadata key="extruder" value="1"/>'
                       '<part id="1" subtype="normal_part">'
                       '<metadata key="name" value="Model 1"/>'
                       '<metadata key="matrix" value="1 0 0 0 0 1 0 0 0 0 1 0 0 0 0 1"/>'
                       '</part></object><object id="2">'
                       '<metadata key="extruder" value="2"/>'
                       '<part id="1" subtype="normal_part"/>'
                       '</object><plate><metadata key="plater_id" value="1"/>'
                       '<metadata key="locked" value="false"/>'
                       '<model_instance><metadata key="object_id" value="1"/>'
                       '<metadata key="instance_id" value="0"/>'
                       '<metadata key="identify_id" value="1"/></model_instance>'
                       '<model_instance><metadata key="object_id" value="2"/>'
                       '<metadata key="instance_id" value="0"/>'
                       '<metadata key="identify_id" value="2"/></model_instance>'
                       '</plate><assemble>'
                       '<assemble_item object_id="1" instance_id="0" '
                       'transform="1 0 0 0 1 0 0 0 1 0 0 0" offset="0 0 0"/>'
                       '<assemble_item object_id="2" instance_id="0" '
                       'transform="1 0 0 0 1 0 0 0 1 0 0 0" offset="0 0 0"/>'
                       '</assemble></config>')
            for name in ("_rels/.rels", "[Content_Types].xml"):
                z.writestr(name, b"bounded structural fixture")
            if identity:
                z.writestr("Metadata/creality.config",
                           '<config><metadata key="Application" value="Creality_Print"/>'
                           '<metadata key="AppVersion" value="7.3.1"/></config>')
            z.writestr("Metadata/project_settings.config", json.dumps(config))
        return data.getvalue()

    @patch("slicer_worker.creality_project_validation.validate_worker_3mf",
           return_value=True)
    def test_native_project_has_embedded_profiles_and_original_plate(self, validate):
        self.assertTrue(validate_creality_project(self.project(), native_tool_count=2))
        validate.assert_called_once()
        self.assertEqual(validate.call_args.kwargs["native_tool_count"], 2)

    def test_real_two_plain_objects_with_two_filament_assignments(self):
        """Real strict worker validator, no mocked 3MF acceptance."""
        import xml.etree.ElementTree as ET
        ns = "{http://schemas.microsoft.com/3dmanufacturing/core/2015/02}"
        archive = io.BytesIO()
        with zipfile.ZipFile(io.BytesIO(self.project())) as source, zipfile.ZipFile(
                archive, "w", compression=zipfile.ZIP_DEFLATED) as dest:
            for name in source.namelist():
                data = source.read(name)
                if name == "3D/3dmodel.model":
                    root = ET.fromstring(data)
                    objects = root.findall("./" + ns + "resources/" + ns + "object")
                    for index, obj in enumerate(objects):
                        obj.set("type", "model")
                        mesh = ET.SubElement(obj, ns + "mesh")
                        vertices = ET.SubElement(mesh, ns + "vertices")
                        shift = index * 12
                        for x, y, z in ((0, 0, 0), (6, 0, 0), (0, 6, 1)):
                            ET.SubElement(vertices, ns + "vertex", {
                                "x": str(x + shift), "y": str(y), "z": str(z)})
                        triangles = ET.SubElement(mesh, ns + "triangles")
                        ET.SubElement(triangles, ns + "triangle", {
                            "v1": "0", "v2": "1", "v3": "2"})
                        ET.SubElement(root.find(ns + "build"), ns + "item", {
                            "objectid": str(index + 1),
                            "transform": "1 0 0 0 1 0 0 0 1 0 0 0"})
                    data = ET.tostring(root, encoding="utf-8")
                dest.writestr(name, data)
        self.assertTrue(validate_creality_project(
            archive.getvalue(), native_tool_count=2))

    @patch("slicer_worker.creality_project_validation.validate_worker_3mf",
           return_value=True)
    def test_plain_two_object_route_does_not_enable_paint_extension(self, validate):
        self.assertTrue(validate_creality_project(
            self.project(), native_tool_count=2))
        self.assertFalse(validate.call_args.kwargs["allow_creality_combined_paint"])

    @patch("slicer_worker.creality_project_validation.validate_worker_3mf",
           return_value=True)
    def test_missing_generator_version_fails_before_engine(self, validate):
        data = self.project()
        import io
        import zipfile
        output = io.BytesIO()
        with zipfile.ZipFile(io.BytesIO(data)) as source, zipfile.ZipFile(
                output, "w", compression=zipfile.ZIP_DEFLATED) as dest:
            for name in source.namelist():
                blob = source.read(name)
                if name == "3D/3dmodel.model":
                    blob = blob.replace(
                        b"Creality_Print V7.3.1", b"MakerVault")
                dest.writestr(name, blob)
        with self.assertRaisesRegex(WorkerError, "generator version"):
            validate_creality_project(output.getvalue())
        validate.assert_not_called()

    @patch("slicer_worker.creality_project_validation.validate_worker_3mf",
           return_value=True)
    def test_one_painted_model_keeps_two_native_filament_tools(self, validate):
        import xml.etree.ElementTree as ET
        source = self.project()
        output = io.BytesIO()
        ns = "{http://schemas.microsoft.com/3dmanufacturing/core/2015/02}"
        with zipfile.ZipFile(io.BytesIO(source)) as original, zipfile.ZipFile(
                output, "w", compression=zipfile.ZIP_DEFLATED) as dest:
            for name in original.namelist():
                raw = original.read(name)
                if name == "3D/3dmodel.model":
                    root = ET.fromstring(raw)
                    resources = root.find(ns + "resources")
                    resources.remove(resources[1])
                    raw = ET.tostring(root, encoding="utf-8")
                elif name == "Metadata/model_settings.config":
                    root = ET.fromstring(raw)
                    records = root.findall("object")
                    root.remove(records[1])
                    plate = root.find("plate")
                    instances = plate.findall("model_instance")
                    plate.remove(instances[1])
                    assembly = root.find("assemble")
                    assembly.remove(assembly[1])
                    raw = ET.tostring(root, encoding="utf-8")
                dest.writestr(name, raw)
        self.assertTrue(validate_creality_project(output.getvalue(),
                                                  native_tool_count=2))
        validate.assert_called_once()
        self.assertEqual(validate.call_args.kwargs["native_tool_count"], 2)
        self.assertTrue(validate.call_args.kwargs["allow_creality_combined_paint"])

    def test_real_worker_accepts_one_painted_mesh_with_two_tools(self):
        """No mocks: exercise the strict native facet/tool validator."""
        import xml.etree.ElementTree as ET
        ns = "{http://schemas.microsoft.com/3dmanufacturing/core/2015/02}"
        raw = self.project()
        output = io.BytesIO()
        with zipfile.ZipFile(io.BytesIO(raw)) as source, zipfile.ZipFile(
                output, "w", compression=zipfile.ZIP_DEFLATED) as dest:
            for name in source.namelist():
                part = source.read(name)
                if name == "3D/3dmodel.model":
                    root = ET.fromstring(part)
                    resources = root.find(ns + "resources")
                    resources.remove(resources[1])
                    obj = resources[0]
                    obj.set("type", "model")
                    mesh = ET.SubElement(obj, ns + "mesh")
                    vertices = ET.SubElement(mesh, ns + "vertices")
                    for x, y, z in ((0, 0, 0), (5, 0, 0), (0, 5, 0)):
                        ET.SubElement(vertices, ns + "vertex", {
                            "x": str(x), "y": str(y), "z": str(z)})
                    triangles = ET.SubElement(mesh, ns + "triangles")
                    ET.SubElement(triangles, ns + "triangle", {
                        "v1": "0", "v2": "1", "v3": "2", "paint_color": "8"})
                    build = root.find(ns + "build")
                    ET.SubElement(build, ns + "item", {
                        "objectid": "1",
                        "transform": "1 0 0 0 1 0 0 0 1 0 0 0",
                    })
                    part = ET.tostring(root, encoding="utf-8")
                elif name == "Metadata/model_settings.config":
                    root = ET.fromstring(part)
                    second = root.findall("object")[1]
                    root.remove(second)
                    plate = root.find("plate")
                    plate.remove(plate.findall("model_instance")[1])
                    assembly = root.find("assemble")
                    assembly.remove(assembly[1])
                    part = ET.tostring(root, encoding="utf-8")
                dest.writestr(name, part)
        self.assertTrue(validate_creality_project(output.getvalue(), native_tool_count=2))

    def _single_painted_project(self, *, semantic=None, layer_xml=None):
        """A real single-model, two-tool fixture validated without mocks."""
        from xml.etree import ElementTree as ET
        ns = "{http://schemas.microsoft.com/3dmanufacturing/core/2015/02}"
        output = io.BytesIO()
        with zipfile.ZipFile(io.BytesIO(self.project())) as src, zipfile.ZipFile(
                output, "w", compression=zipfile.ZIP_DEFLATED) as dst:
            for name in src.namelist():
                blob = src.read(name)
                if name == "3D/3dmodel.model":
                    root = ET.fromstring(blob)
                    resources = root.find(ns + "resources")
                    resources.remove(resources[1])
                    obj = resources[0]
                    obj.set("type", "model")
                    mesh = ET.SubElement(obj, ns + "mesh")
                    vertices = ET.SubElement(mesh, ns + "vertices")
                    for x, y, z in ((0, 0, 0), (5, 0, 0), (0, 5, 0)):
                        ET.SubElement(vertices, ns + "vertex", {
                            "x": str(x), "y": str(y), "z": str(z)})
                    triangles = ET.SubElement(mesh, ns + "triangles")
                    attrs = {"v1": "0", "v2": "1", "v3": "2", "paint_color": "8"}
                    attrs.update(semantic or {})
                    ET.SubElement(triangles, ns + "triangle", attrs)
                    ET.SubElement(root.find(ns + "build"), ns + "item", {
                        "objectid": "1", "transform": "1 0 0 0 1 0 0 0 1 0 0 0"})
                    blob = ET.tostring(root, encoding="utf-8")
                elif name == "Metadata/model_settings.config":
                    root = ET.fromstring(blob)
                    root.remove(root.findall("object")[1])
                    root.find("plate").remove(root.find("plate").findall("model_instance")[1])
                    root.find("assemble").remove(root.find("assemble")[1])
                    blob = ET.tostring(root, encoding="utf-8")
                dst.writestr(name, blob)
            if layer_xml is not None:
                dst.writestr("Metadata/layer_config_ranges.xml", layer_xml)
        return output.getvalue()

    def test_creality_combined_facets_admitted_only_for_known_states(self):
        for channel, state in (
                ("paint_supports", "4"), ("paint_seam", "8"),
                ("paint_fuzzy_skin", "4")):
            with self.subTest(channel=channel):
                self.assertTrue(validate_creality_project(
                    self._single_painted_project(semantic={channel: state})))
                with self.assertRaises(WorkerError):
                    validate_creality_project(self._single_painted_project(
                        semantic={channel: "4;M104 S300"}))
        self.assertTrue(validate_creality_project(self._single_painted_project(
            semantic={"paint_supports": "4", "paint_seam": "8",
                      "paint_fuzzy_skin": "4"})))

    def test_creality_layer_ranges_bounded_and_rejected_if_unsafe(self):
        valid = ('<objects><object id="1"><range min_z="1" max_z="4">'
                 '<option opt_key="layer_height">0.12</option>'
                 '</range></object></objects>')
        self.assertTrue(validate_creality_project(
            self._single_painted_project(layer_xml=valid)))
        for invalid in (
                valid.replace('opt_key="layer_height"', 'opt_key="machine_start_gcode"'),
                valid.replace('id="1"', 'id="999"'),
                valid.replace("0.12", "NaN"),
                valid.replace('max_z="4"', 'max_z="10000"')):
            with self.subTest(xml=invalid), self.assertRaises(WorkerError):
                validate_creality_project(
                    self._single_painted_project(layer_xml=invalid))
        with self.assertRaises(WorkerError):
            validate_creality_project(self._single_painted_project(
                layer_xml="<objects>" + " " * 40000 + "</objects>"))

    def test_missing_creality_identity_is_rejected(self):
        with self.assertRaises(WorkerError):
            validate_creality_project(self.project(identity=False))

    def test_post_processing_cannot_be_embedded_in_native_project(self):
        with self.assertRaisesRegex(WorkerError, "blocked settings"):
            validate_creality_project(
                self.project(project={"post_process": "unsafe"}))

    @patch("slicer_worker.creality_project_validation.validate_worker_3mf",
           return_value=True)
    def test_four_bay_palette_with_two_used_tools(self, validate):
        payload = self.project(project={
            "filament_settings_id": ["grey", "yellow", "grey", "yellow"],
            "filament_map": ["1", "1", "1", "1"],
            "flush_volumes_matrix": ["0"] * 16,
            "flush_volumes_vector": ["140"] * 8,
        })
        self.assertTrue(validate_creality_project(payload, native_tool_count=2))
        validate.assert_called_once()

    def test_inconsistent_native_palette_matrix_is_rejected(self):
        with self.assertRaisesRegex(WorkerError, "purge matrix"):
            validate_creality_project(self.project(project={
                "filament_settings_id": ["grey", "yellow", "grey", "yellow"],
                "flush_volumes_matrix": ["0"] * 4,
            }))

    def test_assembly_cannot_reposition_prepared_models(self):
        data = self.project()
        out = io.BytesIO()
        with zipfile.ZipFile(io.BytesIO(data)) as inp, zipfile.ZipFile(out, "w") as dst:
            for name in inp.namelist():
                raw = inp.read(name)
                if name == "Metadata/model_settings.config":
                    raw = raw.replace(b'transform="1 0 0 0 1 0 0 0 1 0 0 0"',
                                      b'transform="1 0 0 0 1 0 0 0 1 15 0 0"')
                dst.writestr(name, raw)
        with self.assertRaisesRegex(WorkerError, "assembly would modify"):
            validate_creality_project(out.getvalue())

    def test_missing_tool_palette_is_rejected(self):
        with self.assertRaisesRegex(WorkerError, "palette"):
            validate_creality_project(
                self.project(project={"filament_settings_id": ["only one"]}))
