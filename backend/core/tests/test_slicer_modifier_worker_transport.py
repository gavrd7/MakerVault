"""Authenticated modifier worker requests must be explicitly version-scoped."""
import base64
import hashlib
import json
import uuid
from unittest.mock import Mock, patch

from django.test import SimpleTestCase
from core.slicer_worker_client import run_remote_job, SlicerWorkerError


class NativeModifierTransportTests(SimpleTestCase):
    @patch("core.slicer_worker_client._session")
    @patch("core.slicer_worker_client.worker_settings",
           return_value=("http://slicer-worker:8088", "x" * 40))
    def test_exact_native_modifier_contract_is_sent_without_a_palette(
            self, worker, session):
        code = b"G90\nM83\nG1 X1 Y2 E1\n"
        response_bytes = json.dumps({
            "status": "completed", "bytes": len(code),
            "sha256": hashlib.sha256(code).hexdigest(),
            "gcode": base64.b64encode(code).decode(),
        }).encode()
        response = Mock(status_code=200)
        response.headers = {"Content-Length": str(len(response_bytes))}
        response.iter_content.return_value = [response_bytes]
        session.return_value.post.return_value = response
        for engine, version in (("orcaslicer", "2.5.0"),
                                ("crealityprint", "7.3.1"),
                                ("bambustudio", "02.09.01.70")):
            with self.subTest(engine=engine):
                actual = run_remote_job(
                    uuid.uuid4(), engine, version, b"bounded-native-3mf",
                    b"printer", b"filament", b"process",
                    model_format="3mf", native_modifier_project=True)
                self.assertEqual(actual, code)
                body = json.loads(
                    session.return_value.post.call_args.kwargs["data"])
                self.assertIs(body["native_modifier_project"], True)
                self.assertEqual(body["model_format"], "3mf")
                self.assertNotIn("filament_profiles", body)

    @patch("core.slicer_worker_client.worker_settings",
           return_value=("http://slicer-worker:8088", "x" * 40))
    def test_unverified_versions_and_mixed_contracts_are_refused(self, worker):
        base = (uuid.uuid4(), "orcaslicer", "2.5.0",
                b"model", b"printer", b"filament", b"process")
        for engine, version, kwargs in (
            ("orcaslicer", "2.4.2", {"model_format": "3mf"}),
            ("crealityprint", "7.3.0", {"model_format": "3mf"}),
            ("bambustudio", "02.09.01.71", {"model_format": "3mf"}),
            ("prusaslicer", "2.9.7", {"model_format": "3mf"}),
            ("orcaslicer", "2.5.0", {"model_format": "stl"}),
            ("orcaslicer", "2.5.0", {
                "model_format": "3mf",
                "filament_profiles": [b"filament", b"other"]}),
            ("crealityprint", "7.3.1", {
                "model_format": "3mf", "creality_native_project": True}),
        ):
            with self.subTest(engine=engine, version=version), self.assertRaises(SlicerWorkerError):
                run_remote_job(base[0], engine, version, *base[3:],
                               native_modifier_project=True, **kwargs)
