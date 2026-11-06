"""Execution admission must fail closed for mismatched or unverified worker images."""
from unittest.mock import patch
from django.test import SimpleTestCase

from core.slicer_execution import verified_installation


class WorkerApprovalTests(SimpleTestCase):
    def setUp(self):
        self.digest = "sha256:" + "a" * 64
        self.approved = {
            "MAKERVAULT_SLICER_EXECUTION_ENABLED": "1",
            "MAKERVAULT_SLICER_ENGINE_IMAGE_DIGEST": self.digest,
            "MAKERVAULT_SLICER_ENGINE_VERSION": "2.9.7",
            "MAKERVAULT_SLICER_ENGINE": "orcaslicer",
            "MAKERVAULT_SLICER_WORKER_IMAGE": "registry.example.invalid/slicer@" + self.digest,
        }

    @patch("core.slicer_execution.health", return_value={
        "ready": True, "engine": "orcaslicer", "version": "2.9.7",
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
        "ready": False, "engine": "orcaslicer", "version": "2.9.7",
    })
    def test_unready_worker_does_not_enable_slice(self, worker):
        with patch.dict("os.environ", self.approved, clear=True):
            self.assertEqual(verified_installation(), {})
