"""Regressions for the four-running-container slicer layout and process isolation."""
import errno
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import unittest
from unittest.mock import patch

from slicer_worker import combined_service as combined


ROOT = Path(__file__).resolve().parents[2]


class CombinedSlicerTests(unittest.TestCase):
    def test_worker_outbound_connect_fails_closed_inside_child_process(self):
        if sys.platform != "linux" or os.uname().machine != "x86_64":
            self.skipTest("Seccomp integration requires Linux AMD64")
        script = (
            "import errno,socket,sys;"
            "from slicer_worker.combined_service import block_worker_outbound_connections;"
            "block_worker_outbound_connections();"
            "s=socket.socket();"
            "r=s.connect_ex(('127.0.0.1', 1));"
            "sys.exit(0 if r==errno.EPERM else 1)"
        )
        result = subprocess.run([sys.executable, "-c", script], cwd=ROOT,
                                env=os.environ.copy(), capture_output=True,
                                text=True, timeout=10, check=False)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_non_root_supervisor_refuses_to_launch(self):
        with patch.object(combined.os, "geteuid", return_value=10001):
            with self.assertRaises(SystemExit):
                combined.supervise()

    def test_separate_uid_and_token_environment(self):
        from inspect import getsource
        source = getsource(combined.supervise)
        self.assertIn('worker_env.pop("SLICER_INSTALLER_TOKEN", None)', source)
        self.assertIn('installer_env.pop("SLICER_WORKER_TOKEN", None)', source)
        self.assertIn('_spawn("worker", WORKER_UID, worker_env)', source)
        self.assertIn('_spawn("installer", INSTALLER_UID, installer_env)', source)
        self.assertNotEqual(combined.WORKER_UID, combined.INSTALLER_UID)

    def test_compose_has_only_one_slicer_runtime_service(self):
        # Other worker test fixtures may mutate a temporary checkout; verify
        # the committed deployment file, not an incidental working-tree state.
        result = subprocess.run(
            ["git", "show", "HEAD:docker-compose.yml"], cwd=ROOT,
            check=True, capture_output=True, text=True, timeout=10)
        compose = result.stdout
        self.assertIn("  slicer-worker:", compose)
        self.assertNotIn("    profiles: [slicer]", compose)
        self.assertIn("  makervault:", compose)
        self.assertIn("    name: makervault", compose)
        self.assertIn("    container_name: makervault-slicer", compose)
        self.assertNotIn("\n  slicer-engine-installer:", compose)
        self.assertIn("http://slicer-worker:8091", compose)
        self.assertIn("slicer_worker.combined_service", compose)
        self.assertIn("cap_add: [SETUID, SETGID, KILL]", compose)
        self.assertNotIn("\\n  slicer-engine-store-init:", compose)
        dockerfile = (ROOT / "slicer_worker/Dockerfile.generic").read_text()
        self.assertIn("install -d -o 10002 -g 10002", dockerfile)
        self.assertIn("SLICER_ENGINE_STORAGE:-makervault_slicer_engines", compose)
        self.assertNotIn("SLICER_WORKER_ENABLED", compose)

    def test_combined_runtime_has_single_pinned_reviewed_binary(self):
        dockerfile = (ROOT / "slicer_worker/Dockerfile.generic").read_text()
        self.assertIn("ghcr.io/gavrd7/makervault-slicer-orca@sha256:", dockerfile)
        self.assertIn("b30b0ae933e653692cf85a493287a949215ae4c14d547a00203d16dfcadb8054", dockerfile)
        self.assertIn("slicer_worker.combined_service", dockerfile)


if __name__ == "__main__":
    unittest.main()
