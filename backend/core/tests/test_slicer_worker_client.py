import base64
import hashlib
import uuid
from unittest.mock import Mock, patch
from django.test import SimpleTestCase
from core.slicer_worker_client import SlicerWorkerError, run_remote_job, worker_settings


class SlicerWorkerClientTests(SimpleTestCase):
    def test_unconfigured_and_invalid_urls_are_rejected(self):
        with patch.dict("os.environ", {}, clear=True):
            with self.assertRaises(SlicerWorkerError):
                worker_settings()
        with patch.dict("os.environ", {
            "MAKERVAULT_SLICER_WORKER_URL": "http://evil.test/?start=true",
            "MAKERVAULT_SLICER_WORKER_TOKEN": "x" * 40,
        }):
            with self.assertRaises(SlicerWorkerError):
                worker_settings()

    @patch("core.slicer_worker_client._session")
    @patch("core.slicer_worker_client.worker_settings", return_value=("http://slicer-worker:8088", "x" * 40))
    def test_strict_authenticated_transfer_and_checksum(self, settings, session):
        gcode = b"; mock slicer output\nG1 X1 Y2 E1\n"
        response = Mock()
        response.status_code = 200
        response.headers = {"Content-Length": "300"}
        response.iter_content.return_value = [__import__("json").dumps({
            "status": "completed", "gcode": base64.b64encode(gcode).decode(),
            "bytes": len(gcode), "sha256": hashlib.sha256(gcode).hexdigest(),
        }).encode()]
        sender = Mock()
        sender.post.return_value = response
        session.return_value = sender
        result = run_remote_job(uuid.uuid4(), "prusaslicer", "2.9.7", b"stl", b"machine", b"filament", b"process")
        self.assertEqual(result, gcode)
        kwargs = sender.post.call_args.kwargs
        self.assertFalse(kwargs["allow_redirects"])
        self.assertTrue(kwargs["headers"]["Authorization"].startswith("Bearer "))
        self.assertEqual(kwargs["timeout"], (3, 900))
        result = run_remote_job(uuid.uuid4(), "orcaslicer", "2.9.7", b"stl", b"machine", b"filament", b"process")
        self.assertEqual(result, gcode)

    @patch("core.slicer_worker_client._session")
    @patch("core.slicer_worker_client.worker_settings",
           return_value=("http://slicer-worker:8088", "x" * 40))
    def test_worker_profile_rejection_has_specific_allowlisted_category(self, settings, session):
        import json
        response = Mock()
        response.status_code = 422
        response.headers = {"Content-Length": "115"}
        response.iter_content.return_value = [json.dumps({
            "error": "Slicing input or output was rejected.",
            "stage": "running slicer engine", "reason": "unsafe-profile-settings",
        }).encode()]
        session.return_value.post.return_value = response
        with self.assertRaisesRegex(SlicerWorkerError, "unsafe-profile-settings"):
            run_remote_job(uuid.uuid4(), "orcaslicer", "2.4.2",
                           b"model", b"printer", b"filament", b"process")


    @patch("core.slicer_worker_client._session")
    @patch("core.slicer_worker_client.worker_settings",
           return_value=("http://slicer-worker:8088", "x" * 40))
    def test_native_palette_is_encoded_in_order_without_changing_legacy_request(self, settings, session):
        import json
        response = Mock()
        response.status_code = 200
        gcode = b"T0\\nM83\\nG1 X1 E1\\nT1\\nG1 X2 E1\\n"
        payload = json.dumps({
            "status": "completed", "gcode": base64.b64encode(gcode).decode(),
            "bytes": len(gcode), "sha256": hashlib.sha256(gcode).hexdigest(),
        }).encode()
        response.headers = {"Content-Length": str(len(payload))}
        response.iter_content.return_value = [payload]
        session.return_value.post.return_value = response
        result = run_remote_job(uuid.uuid4(), "orcaslicer", "2.4.2",
                                b"3mf", b"printer", b"filament-a", b"process",
                                model_format="3mf",
                                filament_profiles=[b"filament-a", b"filament-b"])
        self.assertEqual(result, gcode)
        sent = json.loads(session.return_value.post.call_args.kwargs["data"])
        self.assertEqual([base64.b64decode(x) for x in sent["filament_profiles"]],
                         [b"filament-a", b"filament-b"])
        self.assertEqual(base64.b64decode(sent["filament_profile"]), b"filament-a")

    def test_invalid_or_unsynchronised_native_palette_is_rejected(self):
        for profiles, engine, model_format in (
            ([b"one"], "orcaslicer", "3mf"),
            ([b"one", b"two"], "orcaslicer", "stl"),
            ([b"one", b"two"], "crealityprint", "3mf"),
            ([b"other", b"two"], "orcaslicer", "3mf"),
            ([b"one", "two"], "orcaslicer", "3mf"),
        ):
            with self.subTest(profiles=profiles, engine=engine, model_format=model_format):
                with self.assertRaises(SlicerWorkerError):
                    run_remote_job(uuid.uuid4(), engine, "2.4.2",
                                   b"model", b"printer", b"one", b"process",
                                   model_format=model_format, filament_profiles=profiles)

    def test_dangerous_engine_or_invalid_inputs_are_rejected_before_transport(self):
        with self.assertRaises(SlicerWorkerError):
            run_remote_job(uuid.uuid4(), "/bin/sh", "1", b"stl", b"p", b"f", b"process")
        with self.assertRaises(SlicerWorkerError):
            run_remote_job("not-uuid", "prusaslicer", "2.9.7", b"stl", b"p", b"f", b"process")

    @patch("core.slicer_worker_client._session")
    @patch("core.slicer_worker_client.worker_settings",
           return_value=("http://slicer-worker:8088", "x" * 40))
    def test_worker_rejection_exposes_only_allowlisted_stage_and_reason(self, settings, session):
        response = Mock()
        response.status_code = 422
        response.headers = {"Content-Length": "120"}
        response.iter_content.return_value = [__import__("json").dumps({
            "stage": "running slicer engine", "reason": "engine-exited",
            "error": "untrusted private data should never appear",
        }).encode()]
        session.return_value.post.return_value = response
        with self.assertRaises(SlicerWorkerError) as caught:
            run_remote_job(uuid.uuid4(), "orcaslicer", "2.4.2",
                           b"model", b"printer", b"filament", b"process")
        self.assertIn("without a recognised diagnostic", str(caught.exception))
        self.assertIn("engine-exited", str(caught.exception))
        self.assertNotIn("untrusted private data", str(caught.exception))

    @patch("core.slicer_worker_client._session")
    @patch("core.slicer_worker_client.worker_settings",
           return_value=("http://slicer-worker:8088", "x" * 40))
    def test_orca_exit_codes_are_translated_not_lost(self, settings, session):
        import json
        for reason, expected in (
            ("cli-validation-exit-238", "settings"),
            ("cli-validation-exit-239", "process preset"),
            ("native-project-settings-invalid", "out-of-range"),
            ("native-profile-load-failed", "native printer"),
        ):
            with self.subTest(reason=reason):
                response = Mock()
                response.status_code = 422
                payload = json.dumps({
                    "stage": "running slicer engine", "reason": reason,
                    "error": "secret/private/model/path",
                }).encode()
                response.headers = {"Content-Length": str(len(payload))}
                response.iter_content.return_value = [payload]
                session.return_value.post.return_value = response
                with self.assertRaises(SlicerWorkerError) as caught:
                    run_remote_job(uuid.uuid4(), "orcaslicer", "2.4.2",
                                   b"model", b"printer", b"filament", b"process")
                self.assertIn(expected, str(caught.exception))
                self.assertIn("[" + reason + "]", str(caught.exception))
                self.assertNotIn("secret/private", str(caught.exception))

    @patch("core.slicer_worker_client._session")
    @patch("core.slicer_worker_client.worker_settings",
           return_value=("http://slicer-worker:8088", "x" * 40))
    def test_unknown_reason_does_not_leak_raw_diagnostics(self, settings, session):
        import json
        response = Mock()
        response.status_code = 422
        payload = json.dumps({"reason": "secret/private/path", "error": "password=secret"}).encode()
        response.headers = {"Content-Length": str(len(payload))}
        response.iter_content.return_value = [payload]
        session.return_value.post.return_value = response
        with self.assertRaises(SlicerWorkerError) as caught:
            run_remote_job(uuid.uuid4(), "orcaslicer", "2.4.2",
                           b"model", b"printer", b"filament", b"process")
        self.assertIn("rejected the job", str(caught.exception))
        self.assertNotIn("password", str(caught.exception))
        self.assertNotIn("secret/private", str(caught.exception))
