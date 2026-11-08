"""Execution admission must fail closed for mismatched or unverified worker images."""
from unittest.mock import patch
from django.test import SimpleTestCase

from core.slicer_execution import verified_installation, _single_unmodified_stl


class WorkerApprovalTests(SimpleTestCase):
    def setUp(self):
        self.digest = "sha256:" + "a" * 64
        self.approved = {
            "MAKERVAULT_SLICER_EXECUTION_ENABLED": "1",
            "MAKERVAULT_SLICER_ENGINE_IMAGE_DIGEST": self.digest,
            "MAKERVAULT_SLICER_ENGINE_VERSION": "2.9.7",
            "MAKERVAULT_SLICER_ENGINE_BINARY_SHA256": "b" * 64,
            "MAKERVAULT_SLICER_ENGINE": "orcaslicer",
            "MAKERVAULT_SLICER_WORKER_IMAGE": "registry.example.invalid/slicer@" + self.digest,
        }

    @patch("core.slicer_execution.health", return_value={
        "ready": True, "engine": "orcaslicer", "version": "2.9.7",
        "binary_sha256": "b" * 64,
    })
    def test_requires_explicit_enablement_matching_digest_and_worker_version(self, worker):
        with patch.dict("os.environ", self.approved, clear=True):
            installed = verified_installation()
            self.assertTrue(installed["orcaslicer"]["verified"])
        for changes in (
            {"MAKERVAULT_SLICER_EXECUTION_ENABLED": "0"},
            {"MAKERVAULT_SLICER_WORKER_IMAGE": "registry/slicer:latest"},
            {"MAKERVAULT_SLICER_ENGINE_IMAGE_DIGEST": "sha256:" + "b" * 64},
            {"MAKERVAULT_SLICER_ENGINE_VERSION": "2.9.6"},
        ):
            with self.subTest(changes=changes):
                with patch.dict("os.environ", {**self.approved, **changes}, clear=True):
                    self.assertEqual(verified_installation(), {})

    @patch("core.slicer_execution.health", return_value={
        "ready": True, "engine": "orcaslicer", "version": "2.9.7",
        "binary_sha256": "b" * 64,
    })
    def test_staging_immutable_local_image_id_is_allowed_only_on_exact_match(self, worker):
        environment = {**self.approved, "MAKERVAULT_SLICER_WORKER_IMAGE": self.digest}
        with patch.dict("os.environ", environment, clear=True):
            self.assertEqual(verified_installation()["orcaslicer"]["image_digest"], self.digest)
        with patch.dict("os.environ", {
            **environment, "MAKERVAULT_SLICER_WORKER_IMAGE": "sha256:" + "f" * 64
        }, clear=True):
            self.assertEqual(verified_installation(), {})

    @patch("core.slicer_execution.health", return_value={
        "ready": True, "engine": "orcaslicer", "version": "2.9.7",
        "binary_sha256": "c" * 64,
    })
    def test_worker_binary_hash_mismatch_disables_execution(self, worker):
        with patch.dict("os.environ", self.approved, clear=True):
            self.assertEqual(verified_installation(), {})

    @patch("core.slicer_execution.health")
    def test_two_independent_approved_engines_share_one_worker(self, worker):
        import json
        worker.return_value = {
            "ready": True,
            "engines": {
                "orcaslicer": {"ready": True, "version": "2.4.2", "binary_sha256": "b" * 64},
                "crealityprint": {"ready": True, "version": "7.3.0", "binary_sha256": "c" * 64},
            },
        }
        approvals = {
            "orcaslicer": {"version": "2.4.2", "binary_sha256": "b" * 64},
            "crealityprint": {"version": "7.3.0", "binary_sha256": "c" * 64},
        }
        settings = {
            **self.approved,
            "MAKERVAULT_SLICER_ENGINES_JSON": json.dumps(approvals),
        }
        with patch.dict("os.environ", settings, clear=True):
            available = verified_installation()
            self.assertEqual(set(available), {"orcaslicer", "crealityprint"})
            self.assertEqual(available["crealityprint"]["version"], "7.3.0")
            worker.return_value["engines"]["orcaslicer"]["binary_sha256"] = "d" * 64
            available = verified_installation()
            self.assertEqual(set(available), {"crealityprint"})
            worker.return_value["engines"]["crealityprint"]["ready"] = False
            self.assertEqual(verified_installation(), {})

    @patch("core.slicer_execution.health", return_value={
        "ready": True,
        "engines": {
            "crealityprint": {"ready": True, "version": "7.3.0", "binary_sha256": "c" * 64},
        },
    })
    def test_creality_only_does_not_require_orca(self, worker):
        import json
        with patch.dict("os.environ", {
            **self.approved,
            "MAKERVAULT_SLICER_ENGINES_JSON": json.dumps({
                "crealityprint": {"version": "7.3.0", "binary_sha256": "c" * 64}
            }),
        }, clear=True):
            self.assertEqual(set(verified_installation()), {"crealityprint"})

    @patch("core.slicer_execution.health", return_value={
        "ready": False, "engine": "orcaslicer", "version": "2.9.7",
        "binary_sha256": "b" * 64,
    })
    def test_unready_worker_does_not_enable_slice(self, worker):
        with patch.dict("os.environ", self.approved, clear=True):
            self.assertEqual(verified_installation(), {})


class PrivateSlicerSourceReadTests(SimpleTestCase):
    def test_repeated_reads_open_fresh_storage_streams(self):
        from io import BytesIO
        from types import SimpleNamespace
        from unittest.mock import MagicMock
        from core.slicer_execution import _read_owned_file

        storage = MagicMock()
        storage.open.side_effect = lambda path, mode: BytesIO(b'{"type":"machine"}')
        field = SimpleNamespace(name="private/ab/opaque.blob", storage=storage)
        asset = SimpleNamespace(pk="asset-id", owner_id=7, file=field)

        self.assertEqual(_read_owned_file(asset, 7, 1024, "Native profile"),
                         b'{"type":"machine"}')
        self.assertEqual(_read_owned_file(asset, 7, 1024, "Native profile"),
                         b'{"type":"machine"}')
        self.assertEqual(storage.open.call_count, 2)
        storage.open.assert_called_with("private/ab/opaque.blob", "rb")


class DirectSingleModelSliceTests(SimpleTestCase):
    def test_unmodified_single_instance_can_use_native_stl_path(self):
        item = {"asset_id": "source", "x_mm": 0, "y_mm": 0,
                "rotation_deg": 0, "scale_percent": 100, "color": "#ffffff"}
        self.assertTrue(_single_unmodified_stl([item]))
        self.assertTrue(_single_unmodified_stl([
            {**item, "scale_xyz_percent": [100, 100, 100]}
        ]))

    def test_transforms_or_multiple_instances_require_project_path(self):
        item = {"asset_id": "source", "x_mm": 0, "y_mm": 0,
                "rotation_deg": 0, "scale_percent": 100}
        self.assertFalse(_single_unmodified_stl([item, item]))
        for changed in (
            {"x_mm": 5}, {"y_mm": -2}, {"rotation_deg": 90},
            {"scale_percent": 120}, {"scale_xyz_percent": [110, 100, 100]},
        ):
            with self.subTest(changed=changed):
                self.assertFalse(_single_unmodified_stl([{**item, **changed}]))
