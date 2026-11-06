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

    def test_dangerous_engine_or_invalid_inputs_are_rejected_before_transport(self):
        with self.assertRaises(SlicerWorkerError):
            run_remote_job(uuid.uuid4(), "/bin/sh", "1", b"stl", b"p", b"f", b"process")
        with self.assertRaises(SlicerWorkerError):
            run_remote_job("not-uuid", "prusaslicer", "2.9.7", b"stl", b"p", b"f", b"process")
