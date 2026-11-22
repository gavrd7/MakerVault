"""Exact MakerVault Bambu 3MF multicolour fixtures and worker admission."""
import base64
import json
import uuid
from unittest import TestCase

from scripts.probe_bambu_multicolour import make_bambu_material_fixture
from slicer_worker.material_gcode_audit import expected_native_tools
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
