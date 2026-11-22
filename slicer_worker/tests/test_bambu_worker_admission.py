"""Opt-in Bambu worker path stays unavailable without exact beta approval."""
import base64
import hashlib
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch
import uuid

from slicer_worker.runner import WorkerError
from slicer_worker.service import _decode_payload
from slicer_worker.engine_registry import (
    configured_engines, BAMBU_BETA_VERSION, BAMBU_BETA_RUNTIME_SHA256,
)


class BambuWorkerAdmissionTests(TestCase):
    def payload(self):
        encoded=lambda raw:base64.b64encode(raw).decode()
        return {
            "job_id": str(uuid.uuid4()), "engine": "bambustudio",
            "engine_version": BAMBU_BETA_VERSION,
            "model": encoded(b"fixture STL"),
            "printer_profile": encoded(b'{"type":"machine","name":"X1C"}'),
            "process_profile": encoded(b'{"type":"process","name":"Standard"}'),
            "filament_profile": encoded(b'{"type":"filament","name":"PLA"}'),
        }

    def test_bambu_payload_denied_by_default_and_enabled_only_for_beta(self):
        with patch.dict(os.environ, {"SLICER_BAMBU_BETA_ENABLED": "0"}, clear=True):
            with self.assertRaisesRegex(WorkerError, "Unsupported isolated worker"):
                _decode_payload(self.payload())
        with patch.dict(os.environ, {"SLICER_BAMBU_BETA_ENABLED": "1"}, clear=True):
            decoded = _decode_payload(self.payload())
            self.assertEqual(decoded["model"], b"fixture STL")
            self.assertEqual(decoded["model_format"], "stl")
            bad = self.payload()
            bad["filament_profiles"] = [bad["filament_profile"]] * 2
            with self.assertRaisesRegex(WorkerError, "Multi-filament"):
                _decode_payload(bad)

    def test_exact_pinned_runtime_and_flag_required_in_static_registry(self):
        with TemporaryDirectory() as tmp:
            path=Path(tmp)/"bambu-run"
            path.write_bytes(b"fixture only")
            path.chmod(0o555)
            entry={"binary":str(path),"version":BAMBU_BETA_VERSION,
                   "binary_sha256":BAMBU_BETA_RUNTIME_SHA256}
            env={
                "SLICER_WORKER_ENABLED":"1",
                "SLICER_WORKER_TOKEN":"x"*48,
                "SLICER_ENGINES_JSON":json.dumps({"bambustudio":entry}),
                "SLICER_BAMBU_BETA_ENABLED":"0",
            }
            with patch("slicer_worker.engine_registry._read_active_manifest", return_value=None),\
                 patch("slicer_worker.engine_registry._hash_binary", return_value=BAMBU_BETA_RUNTIME_SHA256),\
                 patch.dict(os.environ,env,clear=True):
                self.assertEqual(configured_engines(), {})
                os.environ["SLICER_BAMBU_BETA_ENABLED"]="1"
                self.assertEqual(configured_engines()["bambustudio"]["version"],BAMBU_BETA_VERSION)
                entry["binary_sha256"] = "0"*64
                os.environ["SLICER_ENGINES_JSON"]=json.dumps({"bambustudio":entry})
                self.assertEqual(configured_engines(), {})
                entry["binary_sha256"]=BAMBU_BETA_RUNTIME_SHA256
                entry["version"]="02.10.00.00"
                os.environ["SLICER_ENGINES_JSON"]=json.dumps({"bambustudio":entry})
                self.assertEqual(configured_engines(), {})
