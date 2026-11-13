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

    def test_exact_binary_checksum_is_required_without_launching_the_slicer(self):
        import hashlib
        from tempfile import TemporaryDirectory
        from pathlib import Path
        with TemporaryDirectory() as tmp:
            binary = Path(tmp) / "orca"
            binary.write_bytes(b"verified fixture engine")
            binary.chmod(0o700)
            settings = {
                "SLICER_WORKER_ENABLED": "1",
                "SLICER_WORKER_TOKEN": "x" * 40,
                "SLICER_ENGINE": "orcaslicer",
                "SLICER_ENGINE_BINARY": str(binary),
                "SLICER_ENGINE_VERSION": "2.4.2",
                "SLICER_ENGINE_BINARY_SHA256": hashlib.sha256(binary.read_bytes()).hexdigest(),
            }
            with patch.dict(os.environ, settings, clear=True):
                self.assertEqual(configured_engine()["engine"], "orcaslicer")
                self.assertEqual(configured_engine()["binary_sha256"], settings["SLICER_ENGINE_BINARY_SHA256"])
            with patch.dict(os.environ, {**settings, "SLICER_ENGINE_BINARY_SHA256": "0" * 64}, clear=True):
                self.assertIsNone(configured_engine())
            with patch.dict(os.environ, {k: v for k, v in settings.items() if k != "SLICER_ENGINE_BINARY_SHA256"}, clear=True):
                self.assertIsNone(configured_engine())


    def test_multi_filament_payload_rejects_malformed_and_cross_engine_palettes(self):
        import io
        import zipfile
        from unittest.mock import patch
        payload = self.payload()
        payload["engine"] = "orcaslicer"
        payload["model_format"] = "3mf"
        profile = payload["filament_profile"]
        payload["filament_profiles"] = [profile, profile]
        # Geometry validity is tested separately; isolate protocol validation.
        with patch("slicer_worker.service.validate_worker_3mf") as validate:
            decoded = _decode_payload(payload)
            self.assertEqual(decoded["filament_profiles"], [b"filament = 1"] * 2)
            validate.assert_called_once_with(decoded["model"], native_tool_count=2)
        for change in (
            {"engine": "prusaslicer"},
            {"model_format": "stl"},
            {"filament_profiles": [profile]},
            {"filament_profiles": [profile, "not-base64"]},
            {"filament_profiles": [profile, base64.b64encode(b"other").decode()]},
            {"filament_profiles": "not-a-list"},
        ):
            with self.subTest(change=change):
                with self.assertRaises(WorkerError):
                    _decode_payload({**payload, **change})

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


class MultiEngineInventoryTests(TestCase):
    def test_orca_and_creality_can_be_approved_independently(self):
        import hashlib
        import json
        from pathlib import Path
        from tempfile import TemporaryDirectory
        from slicer_worker.engine_registry import configured_engines
        with TemporaryDirectory() as root:
            a = Path(root) / "orca"
            b = Path(root) / "creality"
            for item in (a, b):
                item.write_bytes(b"mock test fixture " + item.name.encode())
                item.chmod(0o700)
            entries = {
                "orcaslicer": {"binary": str(a), "version": "2.4.2",
                               "binary_sha256": hashlib.sha256(a.read_bytes()).hexdigest()},
                "crealityprint": {"binary": str(b), "version": "7.3.0",
                                  "binary_sha256": hashlib.sha256(b.read_bytes()).hexdigest()},
            }
            env = {"SLICER_WORKER_ENABLED": "1", "SLICER_WORKER_TOKEN": "x" * 40,
                   "SLICER_ENGINES_JSON": json.dumps(entries)}
            with patch.dict(os.environ, env, clear=True):
                self.assertEqual(set(configured_engines()), set(entries))
                entries["orcaslicer"]["binary_sha256"] = "0" * 64
                with patch.dict(os.environ, {**env, "SLICER_ENGINES_JSON": json.dumps(entries)}, clear=True):
                    # An invalid Orca binary must not disable verified Creality.
                    self.assertEqual(set(configured_engines()), {"crealityprint"})

    def test_only_creality_does_not_require_orca(self):
        import hashlib
        import json
        from pathlib import Path
        from tempfile import TemporaryDirectory
        from slicer_worker.engine_registry import configured_engines
        with TemporaryDirectory() as root:
            binary = Path(root) / "creality"
            binary.write_bytes(b"test-only fixture")
            binary.chmod(0o700)
            with patch.dict(os.environ, {
                "SLICER_WORKER_ENABLED": "1", "SLICER_WORKER_TOKEN": "x" * 40,
                "SLICER_ENGINES_JSON": json.dumps({
                    "crealityprint": {"binary": str(binary), "version": "7.3.0",
                                      "binary_sha256": hashlib.sha256(binary.read_bytes()).hexdigest()},
                }),
            }, clear=True):
                self.assertEqual(set(configured_engines()), {"crealityprint"})


class SlicerWorkerConcurrencyTests(TestCase):
    def test_worker_slot_allows_one_active_slice(self):
        from slicer_worker.service import SLICE_SLOT
        self.assertTrue(SLICE_SLOT.acquire(blocking=False))
        try:
            self.assertFalse(SLICE_SLOT.acquire(blocking=False))
        finally:
            SLICE_SLOT.release()
        self.assertTrue(SLICE_SLOT.acquire(blocking=False))
        SLICE_SLOT.release()


class WorkerHttpConnectionLimitTests(TestCase):
    def test_worker_server_limit_is_independent_of_one_slice_slot(self):
        from unittest.mock import Mock
        from slicer_worker.service import BoundedWorkerHTTPServer, MAX_WORKER_CONNECTIONS
        self.assertLessEqual(MAX_WORKER_CONNECTIONS, 16)
        server = object.__new__(BoundedWorkerHTTPServer)
        from threading import BoundedSemaphore
        server._connections = BoundedSemaphore(MAX_WORKER_CONNECTIONS)
        closed = []
        server.shutdown_request = lambda request: closed.append(request)
        with patch("slicer_worker.service.ThreadingHTTPServer.process_request") as dispatch:
            for i in range(MAX_WORKER_CONNECTIONS):
                server.process_request(i, ("127.0.0.1", i))
            self.assertEqual(dispatch.call_count, MAX_WORKER_CONNECTIONS)
            server.process_request("overflow", ("127.0.0.1", 1234))
            self.assertEqual(closed, ["overflow"])
