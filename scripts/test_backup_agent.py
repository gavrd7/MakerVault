import importlib.util
import io
import json
from pathlib import Path
import tarfile
import tempfile
import unittest
from unittest.mock import patch


spec = importlib.util.spec_from_file_location(
    "backup_agent",
    Path(__file__).resolve().parents[1] / "docker" / "backup_agent.py",
)
agent = importlib.util.module_from_spec(spec)
spec.loader.exec_module(agent)


class BackupAgentTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        root = Path(self.directory.name)
        self.backups = root / "backups"
        self.media = root / "media"
        self.keys = root / "keys"
        self.config = root / "config"
        for path in (self.backups, self.media, self.keys, self.config):
            path.mkdir()
        (self.media / "example.txt").write_text("media", encoding="utf-8")
        (self.keys / "private_storage.key").write_text("synthetic-key", encoding="utf-8")
        (self.config / ".env").write_text("SYNTHETIC=true\n", encoding="utf-8")
        (self.config / "compose.yaml").write_text("services: {}\n", encoding="utf-8")

        self.original = (
            agent.BACKUP_ROOT,
            agent.MEDIA_ROOT,
            agent.KEY_ROOT,
            agent.CONFIG_ROOT,
            agent.LOCK_FILE,
            agent._running_id,
        )
        agent.BACKUP_ROOT = self.backups
        agent.MEDIA_ROOT = self.media
        agent.KEY_ROOT = self.keys
        agent.CONFIG_ROOT = self.config
        agent.LOCK_FILE = self.backups / ".maintenance-lock"
        agent._running_id = ""
        self.addCleanup(self.restore_globals)

    def restore_globals(self):
        (
            agent.BACKUP_ROOT,
            agent.MEDIA_ROOT,
            agent.KEY_ROOT,
            agent.CONFIG_ROOT,
            agent.LOCK_FILE,
            agent._running_id,
        ) = self.original

    def fake_subprocess(self, command, **kwargs):
        if command[0] == "pg_dump":
            kwargs["stdout"].write(b"synthetic-postgres-dump")
        return agent.subprocess.CompletedProcess(command, 0, stdout=b"", stderr=b"")

    def test_create_bundle_is_verified_and_clears_lock(self):
        with patch.object(agent.subprocess, "run", side_effect=self.fake_subprocess):
            item = agent.create_bundle(backup_id="unit-test", label="Unit test")
        self.assertEqual(item["status"], "complete")
        self.assertTrue(item["verified"])
        self.assertTrue((self.backups / "unit-test.mvbackup").is_file())
        self.assertFalse(agent.LOCK_FILE.exists())
        saved = json.loads((self.backups / "unit-test.json").read_text(encoding="utf-8"))
        self.assertEqual(saved["status"], "complete")

    def test_invalid_identifier_is_rejected(self):
        with self.assertRaises(agent.BackupError):
            agent.safe_id("../escape")

    def test_validation_rejects_path_traversal(self):
        bundle = self.backups / "unsafe.mvbackup"
        with tarfile.open(bundle, "w:gz") as archive:
            info = tarfile.TarInfo("../escape")
            payload = b"unsafe"
            info.size = len(payload)
            archive.addfile(info, io.BytesIO(payload))
        with self.assertRaises(agent.BackupError):
            agent.validate_bundle(bundle)

    def test_failed_backup_clears_lock_and_records_failure(self):
        def fail_dump(command, **kwargs):
            if command[0] == "pg_dump":
                return agent.subprocess.CompletedProcess(command, 1, stderr=b"synthetic dump failure")
            return agent.subprocess.CompletedProcess(command, 0, stdout=b"", stderr=b"")

        with patch.object(agent.subprocess, "run", side_effect=fail_dump):
            with self.assertRaises(agent.BackupError):
                agent.create_bundle(backup_id="failed-test")
        self.assertFalse(agent.LOCK_FILE.exists())
        saved = json.loads((self.backups / "failed-test.json").read_text(encoding="utf-8"))
        self.assertEqual(saved["status"], "failed")
        self.assertFalse(saved["verified"])


if __name__ == "__main__":
    unittest.main()
