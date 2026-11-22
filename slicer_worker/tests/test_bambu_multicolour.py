"""Exact MakerVault Bambu 3MF multicolour fixtures and worker admission."""
import base64
import json
import uuid
from unittest import TestCase

from scripts.probe_bambu_multicolour import make_bambu_material_fixture
from slicer_worker.material_gcode_audit import expected_native_tools, verify_painted_cube_tool_regions
from slicer_worker.service import _decode_payload
from slicer_worker.runner import WorkerError
from slicer_worker.three_mf_validation import validate_worker_3mf


class BambuNativeMulticolourTests(TestCase):
    def payload(self, model):
        encoded = lambda data: base64.b64encode(data).decode("ascii")
        filament0 = b'{"type":"filament","name":"Bambu PLA A"}'
        filament1 = b'{"type":"filament","name":"Bambu PLA B"}'
        return {
            "job_id": str(uuid.uuid4()), "engine": "bambustudio",
            "engine_version": "02.09.01.70", "model_format": "3mf",
            "model": encoded(model),
            "printer_profile": encoded(b'{"type":"machine","name":"Bambu X1C"}'),
            "process_profile": encoded(b'{"type":"process","name":"Standard"}'),
            "filament_profile": encoded(filament0),
            "filament_profiles": [encoded(filament0), encoded(filament1)],
        }

    def test_painted_cube_deposition_audit_rejects_purge_only(self):
        def toolpaths(painted_inside):
            lines = ["G90", "M83", "T0", "G1 X75 Y110 E0.2"] * 20
            lines += ["T1"]
            if painted_inside:
                lines += ["G1 X80 Y110 E0.2"] * 20
            else:
                lines += ["G1 X30 Y30 E0.2"] * 20
            return ("\n".join(lines) + "\n").encode("utf-8")
        with self.assertRaisesRegex(WorkerError, "inside the model"):
            verify_painted_cube_tool_regions(toolpaths(False))
        counts = verify_painted_cube_tool_regions(toolpaths(True))
        self.assertGreaterEqual(counts["base_tool_model_deposits"], 10)
        self.assertGreaterEqual(counts["painted_tool_model_deposits"], 10)

    def test_painted_cube_deposition_audit_tracks_relative_xy_without_false_purge(self):
        lines = ["G90", "M83", "T0"]
        lines.extend(["G1 X75 Y110 E0.2"] * 20)
        lines.extend(["T1", "G91"])
        lines.extend(["G1 X1 Y0 E0.2", "G1 X-1 Y0 E0.2"] * 10)
        raw = ("\n".join(lines) + "\n").encode("utf-8")
        counts = verify_painted_cube_tool_regions(raw)
        self.assertGreaterEqual(counts["base_tool_model_deposits"], 10)
        self.assertGreaterEqual(counts["painted_tool_model_deposits"], 10)

    def test_two_object_tool_assignments_are_preserved(self):
        project = make_bambu_material_fixture()
        self.assertTrue(validate_worker_3mf(project, native_tool_count=2, allow_bambu_project=True))
        self.assertEqual(expected_native_tools(project), {0, 1})
        decoded = _decode_payload(self.payload(project))
        self.assertEqual(decoded["model_format"], "3mf")
        self.assertEqual(len(decoded["filament_profiles"]), 2)

    def test_single_model_native_paint_color_selects_second_tool(self):
        project = make_bambu_material_fixture(painted=True)
        self.assertTrue(validate_worker_3mf(project, native_tool_count=2, allow_bambu_project=True))
        self.assertEqual(expected_native_tools(project), {0, 1})
        self.assertEqual(len(_decode_payload(self.payload(project))["filament_profiles"]), 2)

    def test_native_project_settings_are_never_accepted_by_orca_contract(self):
        project = make_bambu_material_fixture()
        with self.assertRaisesRegex(WorkerError, "Unsupported 3MF package members"):
            validate_worker_3mf(project, native_tool_count=2)
        request = self.payload(project)
        request["engine"] = "orcaslicer"
        with self.assertRaisesRegex(WorkerError, "Unsupported 3MF package members"):
            _decode_payload(request)

    def test_bambu_combined_colour_and_support_paint_requires_native_palette(self):
        import io
        import zipfile
        from xml.etree import ElementTree as ET
        project = make_bambu_material_fixture(painted=True)
        with zipfile.ZipFile(io.BytesIO(project)) as source:
            members = {name: source.read(name) for name in source.namelist()}
        root = ET.fromstring(members["3D/3dmodel.model"])
        painted = next(node for node in root.iter()
                       if node.tag.endswith("}triangle") and node.get("paint_color") == "8")
        painted.set("paint_supports", "4")
        members["3D/3dmodel.model"] = ET.tostring(root, encoding="utf-8")
        with io.BytesIO() as output:
            with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as dest:
                for name, data in members.items():
                    dest.writestr(name, data)
            combined = output.getvalue()
        with self.assertRaisesRegex(WorkerError, "painted facet"):
            validate_worker_3mf(combined, native_tool_count=2,
                                allow_bambu_project=True)
        self.assertTrue(validate_worker_3mf(
            combined, native_tool_count=2, allow_bambu_project=True,
            allow_bambu_combined_paint=True))
        self.assertEqual(len(_decode_payload(self.payload(combined))["filament_profiles"]), 2)

    def test_bambu_multifilament_refuses_project_without_vendor_filament_vectors(self):
        import io
        import zipfile
        project = make_bambu_material_fixture()
        with zipfile.ZipFile(io.BytesIO(project)) as original:
            members = {name: original.read(name) for name in original.namelist()
                       if name != "Metadata/project_settings.config"}
        with io.BytesIO() as output:
            with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as target:
                for name, data in members.items():
                    target.writestr(name, data)
            missing = output.getvalue()
        with self.assertRaisesRegex(WorkerError, "requires native project settings"):
            _decode_payload(self.payload(missing))

    def test_bambu_project_rejects_missing_or_invalid_printable_height(self):
        import io
        import zipfile
        project = make_bambu_material_fixture()
        with zipfile.ZipFile(io.BytesIO(project)) as original:
            members = {name: original.read(name) for name in original.namelist()}
        for value in (None, "", "-1", "0", "NaN", "Infinity", "2001",
                      "../../etc/passwd", ["256"]):
            project_settings = json.loads(members["Metadata/project_settings.config"])
            if value is None:
                del project_settings["printable_height"]
            else:
                project_settings["printable_height"] = value
            with io.BytesIO() as output:
                with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as target:
                    for name, data in members.items():
                        if name == "Metadata/project_settings.config":
                            data = json.dumps(project_settings).encode()
                        target.writestr(name, data)
                invalid = output.getvalue()
            with self.subTest(value=value):
                with self.assertRaisesRegex(WorkerError, "printable height"):
                    validate_worker_3mf(
                        invalid, native_tool_count=2, allow_bambu_project=True)

    def test_worker_rejects_wrong_filament_order_and_non_3mf_input(self):
        project = make_bambu_material_fixture()
        request = self.payload(project)
        request["filament_profile"] = request["filament_profiles"][1]
        with self.assertRaisesRegex(WorkerError, "first preset"):
            _decode_payload(request)
        request = self.payload(project)
        request["model_format"] = "stl"
        with self.assertRaises(WorkerError):
            _decode_payload(request)
        request = self.payload(project)
        request["filament_profiles"].pop()
        with self.assertRaisesRegex(WorkerError, "Multi-filament"):
            _decode_payload(request)
