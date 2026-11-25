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

    def test_prusa_unverified_native_3mf_is_rejected_before_validation(self):
        payload = {**self.payload(), "model_format": "3mf"}
        with patch("slicer_worker.service.validate_worker_3mf") as native:
            with self.assertRaisesRegex(WorkerError, "Prusa native 3MF"):
                _decode_payload(payload)
            native.assert_not_called()

    def test_prusa_placed_stl_is_opt_in_and_exactly_engine_version_scoped(self):
        payload = {**self.payload(), "prusa_placed_stl": True}
        decoded = _decode_payload(payload)
        self.assertTrue(decoded["prusa_placed_stl"])
        for change in (
            {"prusa_placed_stl": False},
            {"prusa_placed_stl": 1},
            {"engine": "orcaslicer"},
            {"engine_version": "2.9.6"},
            {"model_format": "3mf"},
            {"filament_profiles": [payload["filament_profile"]] * 2},
            {"creality_native_project": True},
            {"native_modifier_project": True},
        ):
            with self.subTest(change=change):
                with self.assertRaises(WorkerError):
                    _decode_payload({**payload, **change})

    def test_creality_multi_stl_contract_uses_distinct_one_based_tools(self):
        import struct
        stl = (b"fixture".ljust(80, b" ") + struct.pack(
            "<I12fH", 1, 0, 0, 1, 0, 0, 0,
            10, 0, 0, 0, 10, 0, 0))
        encoded = base64.b64encode(stl).decode()
        profile = self.payload()["filament_profile"]
        payload = {**self.payload(),
                   "engine": "crealityprint", "engine_version": "7.3.1",
                   "model": encoded,
                   "filament_profiles": [profile, profile],
                   "creality_model_stls": [encoded, encoded],
                   "creality_tool_ids": [2, 1]}
        decoded = _decode_payload(payload)
        self.assertEqual(decoded["creality_tool_ids"], [2, 1])
        self.assertEqual(decoded["creality_model_stls"], [stl, stl])
        for changes in (
            {"creality_tool_ids": [0, 1]},
            {"creality_tool_ids": [1, 1]},
            {"creality_tool_ids": [1, 3]},
            {"creality_tool_ids": ["1", "2"]},
            {"creality_tool_ids": [1]},
            {"model_format": "3mf"},
            {"engine": "orcaslicer"},
        ):
            with self.subTest(changes=changes):
                with self.assertRaises(WorkerError):
                    _decode_payload({**payload, **changes})

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

class NativeValidationReasonContractTests(TestCase):
    def test_static_native_validator_rejections_are_safely_categorised(self):
        # When a worker rejects a structurally invalid 3MF, its exact static
        # refusal must be mapped to a bounded client-visible reason, not the
        # unhelpful catch-all validation-error.
        import re
        from pathlib import Path
        root = Path(__file__).resolve().parents[1]
        validator = root.joinpath("three_mf_validation.py").read_text()
        service = root.joinpath("service.py").read_text()
        literals = set(re.findall(r'raise WorkerError\(\s*"([^"]+)', validator))
        self.assertTrue(literals)
        for message in sorted(literals):
            with self.subTest(message=message):
                self.assertIn('"' + message + '":', service)

    def test_all_native_multicolour_reasons_have_safe_client_explanations(self):
        # Keep worker refusal categories and backend-readable explanations in
        # lockstep, never forwarding arbitrary profile or 3MF strings.
        from pathlib import Path
        source = Path(__file__).resolve().parents[1].joinpath("service.py").read_text()
        for raw, reason in (
            ("Every native object must select a tool and two native tools must be used.", "native-tool-use-mismatch"),
            ("Painted colour refers to an unavailable native filament.", "native-paint-tool-out-of-range"),
            ("Colour painting requires verified native multi-tool slicing.", "native-paint-channel-conflict"),
            ("Invalid native object extruder.", "native-object-tool-invalid"),
            ("Multi-filament 3MF requires native object assignments.", "native-object-tool-missing"),
            ("Native filament palette does not match its first preset.", "native-filament-palette-mismatch"),
        ):
            with self.subTest(reason=reason):
                self.assertIn(raw, source)
                self.assertIn('"' + reason + '"', source)
