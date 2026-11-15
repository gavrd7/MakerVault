from django.test import SimpleTestCase

from core.management.commands.diagnose_slicer_engine import inspect_slicer_worker
from core.slicer_worker_client import SlicerWorkerError


class SlicerEngineDiagnosisTests(SimpleTestCase):
    def setUp(self):
        self.digest = "sha256:" + "a" * 64
        self.env = {
            "MAKERVAULT_SLICER_EXECUTION_ENABLED": "1",
            "MAKERVAULT_SLICER_ENGINE_IMAGE_DIGEST": self.digest,
            "MAKERVAULT_SLICER_WORKER_IMAGE": self.digest,
            "MAKERVAULT_SLICER_ENGINES_JSON": '{"orcaslicer":{"version":"2.5.0","binary_sha256":"' + "b"*64 + '"}}',
        }

    def test_disabled_and_unpinned_workflows_have_specific_safe_errors(self):
        self.assertEqual(inspect_slicer_worker({})["status"], "disabled")
        bad = {**self.env, "MAKERVAULT_SLICER_WORKER_IMAGE": "worker:latest"}
        self.assertEqual(inspect_slicer_worker(bad)["status"], "image_mismatch")
        bad = {**self.env, "MAKERVAULT_SLICER_ENGINES_JSON": "not-json"}
        self.assertEqual(inspect_slicer_worker(bad)["status"], "approval_missing")

    def test_unreachable_unready_mismatch_and_ready_are_distinct(self):
        def unreachable():
            raise SlicerWorkerError("private-url token-abc")
        self.assertEqual(inspect_slicer_worker(self.env, probe=unreachable)["status"], "unreachable")
        self.assertEqual(inspect_slicer_worker(
            self.env, probe=lambda: {"ready": False})["status"], "worker_unready")
        self.assertEqual(inspect_slicer_worker(
            self.env, probe=lambda: {"ready": True}, approvals=lambda: {})["status"], "identity_mismatch")
        state = inspect_slicer_worker(
            self.env, probe=lambda: {"ready": True},
            approvals=lambda: {"orcaslicer": {"verified": True}})
        self.assertEqual(state["status"], "ready")
        self.assertEqual(state["engines"], ["orcaslicer"])
        self.assertNotIn("token-abc", str(state))
        self.assertNotIn(self.digest, str(state))
