import json
from pathlib import Path
import subprocess
import tempfile
from unittest.mock import patch

from django.test import TestCase, override_settings

from core import backup_bundle


class ManagedBackupBundleTests(TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        root = Path(self.directory.name)
        self.backups = root / "backups"
        self.media = root / "media"
        self.keys = root / "keys"
        self.tls = self.keys / "tls"
        for path in (self.backups, self.media, self.keys):
            path.mkdir()
        self.tls.mkdir()
        (self.media / "example.txt").write_text("media-original", encoding="utf-8")
        (self.keys / "private_storage.key").write_text("synthetic-key", encoding="utf-8")
        (self.tls / "cert.pem").write_text("synthetic-cert", encoding="utf-8")
        (self.tls / "key.pem").write_text("synthetic-tls-key", encoding="utf-8")

        self.override = override_settings(
            MAKERVAULT_BACKUP_ROOT=self.backups,
            MEDIA_ROOT=self.media,
            MAKERVAULT_STORAGE_KEY_FILE=self.keys / "private_storage.key",
        )
        self.override.enable()
        self.addCleanup(self.override.disable)
        self.env_patch = patch.dict("os.environ", {"MAKERVAULT_TLS_ROOT": str(self.tls)}, clear=False)
        self.env_patch.start()
        self.addCleanup(self.env_patch.stop)

    def fake_subprocess(self, command, **kwargs):
        if command[0] == "pg_dump":
            kwargs["stdout"].write(b"synthetic-postgres-dump")
        return subprocess.CompletedProcess(command, 0, stdout=b"", stderr=b"")

    def test_create_bundle_is_verified_and_clears_lock(self):
        with patch.object(backup_bundle.subprocess, "run", side_effect=self.fake_subprocess),              patch.object(backup_bundle, "_recovery_env_keys", return_value=["DJANGO_SECRET_KEY"]),              patch.dict("os.environ", {"DJANGO_SECRET_KEY": "synthetic-secret"}, clear=False):
            item = backup_bundle.create_bundle(backup_id="integrated-test", label="Unit test")

        self.assertEqual(item["status"], "complete")
        self.assertTrue(item["verified"])
        self.assertTrue((self.backups / "integrated-test.mvbackup").is_file())
        self.assertFalse(backup_bundle.maintenance_lock_path().exists())

        with patch.object(backup_bundle.subprocess, "run", side_effect=self.fake_subprocess):
            validation = backup_bundle.validate_backup_id("integrated-test")
        self.assertTrue(validation["valid"])
        self.assertEqual(validation["format_version"], backup_bundle.FORMAT_VERSION)

    def test_second_backup_cannot_claim_existing_lock(self):
        backup_bundle.prepare_backup(backup_id="first")
        self.addCleanup(backup_bundle.release_lock, "first")
        with self.assertRaises(backup_bundle.BackupBundleError):
            backup_bundle.prepare_backup(backup_id="second")

    def test_failed_dump_marks_backup_failed_and_releases_lock(self):
        def fail_dump(command, **kwargs):
            if command[0] == "pg_dump":
                raise subprocess.CalledProcessError(
                    1, command, stderr=b"synthetic dump failure"
                )
            return subprocess.CompletedProcess(command, 0, stdout=b"", stderr=b"")

        with patch.object(backup_bundle.subprocess, "run", side_effect=fail_dump):
            with self.assertRaises(backup_bundle.BackupBundleError):
                backup_bundle.create_bundle(backup_id="failed-test")

        self.assertFalse(backup_bundle.maintenance_lock_path().exists())
        saved = json.loads(
            (self.backups / "failed-test.json").read_text(encoding="utf-8")
        )
        self.assertEqual(saved["status"], "failed")
        self.assertFalse(saved["verified"])

    def test_restore_replaces_media_key_and_tls_from_bundle(self):
        with patch.object(backup_bundle.subprocess, "run", side_effect=self.fake_subprocess):
            backup_bundle.create_bundle(backup_id="restore-test")

        (self.media / "example.txt").write_text("changed-media", encoding="utf-8")
        (self.keys / "private_storage.key").write_text("changed-key", encoding="utf-8")
        (self.media / "newer.txt").write_text("newer", encoding="utf-8")
        (self.tls / "cert.pem").write_text("changed-cert", encoding="utf-8")
        (self.tls / "key.pem").write_text("changed-tls-key", encoding="utf-8")

        with patch.object(backup_bundle.subprocess, "run", side_effect=self.fake_subprocess):
            backup_bundle.restore_bundle("restore-test")

        self.assertEqual(
            (self.media / "example.txt").read_text(encoding="utf-8"),
            "media-original",
        )
        self.assertEqual(
            (self.keys / "private_storage.key").read_text(encoding="utf-8"),
            "synthetic-key",
        )
        self.assertFalse((self.media / "newer.txt").exists())
        self.assertEqual((self.tls / "cert.pem").read_text(encoding="utf-8"), "synthetic-cert")
        self.assertEqual((self.tls / "key.pem").read_text(encoding="utf-8"), "synthetic-tls-key")

    def test_startup_recovery_clears_interrupted_job(self):
        backup_bundle.prepare_backup(backup_id="interrupted")
        count = backup_bundle.recover_interrupted_backups()
        self.assertEqual(count, 1)
        self.assertFalse(backup_bundle.maintenance_lock_path().exists())
        saved = json.loads(
            (self.backups / "interrupted.json").read_text(encoding="utf-8")
        )
        self.assertEqual(saved["status"], "failed")
        self.assertIn("restarted", saved["error"])
