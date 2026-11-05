import base64
import os
from unittest import TestCase
from unittest.mock import patch
import uuid

from slicer_worker.service import _decode_payload, configured_engine
from slicer_worker.runner import WorkerError


class SlicerWorkerProtocolTests(TestCase):
    def payload(self):
        return {
            "job_id": str(uuid.uuid4()), "engine": "prusaslicer",
            "engine_version": "2.9.7",
            "model": base64.b64encode(b"stl").decode(),
            "printer_profile": base64.b64encode(b"printer = 1").decode(),
            "filament_profile": base64.b64encode(b"filament = 1").decode(),
            "process_profile": base64.b64encode(b"layer_height = 0.2").decode(),
        }

    def test_disabled_by_default_even_when_binary_settings_present(self):
        with patch.dict(os.environ, {
            "SLICER_WORKER_ENABLED": "0", "SLICER_WORKER_TOKEN": "secret" * 10,
            "SLICER_PRUSA_BINARY": "/usr/bin/prusa-slicer",
            "SLICER_PRUSA_VERSION": "2.9.7",
        }):
            self.assertIsNone(configured_engine())

    def test_fixed_payload_accepts_only_bounded_inputs(self):
        decoded = _decode_payload(self.payload())
        self.assertEqual(decoded["model"], b"stl")
        for invalid in (
            {"cmd": "rm -rf /"},
            {"model": "!!not-base64!!"},
            {"job_id": "../../../../"},
            {"engine": "arbitrary"},
            {"printer_profile": ""},
        ):
            with self.subTest(invalid=invalid):
                with self.assertRaises(WorkerError):
                    _decode_payload({**self.payload(), **invalid})
