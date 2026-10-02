import json
from pathlib import Path
import tempfile
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings


class BackupApiTests(TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.override = override_settings(MAKERVAULT_BACKUP_ROOT=Path(self.directory.name))
        self.override.enable()
        self.addCleanup(self.override.disable)
        User = get_user_model()
        self.superuser = User.objects.create_superuser(username="backup-admin", password="test-password-12345")
        self.staff = User.objects.create_user(username="backup-staff", password="test-password-12345", is_staff=True)

    def write_backup(self, backup_id="20261002-test", status="complete", verified=True):
        root = Path(self.directory.name)
        bundle = root / f"{backup_id}.mvbackup"
        bundle.write_bytes(b"synthetic bundle")
        metadata = {
            "id": backup_id,
            "label": "Test backup",
            "filename": bundle.name,
            "status": status,
            "verified": verified,
            "created_at": "2026-10-02T08:00:00Z",
            "finished_at": "2026-10-02T08:01:00Z",
            "size_bytes": bundle.stat().st_size,
            "format_version": 2,
        }
        (root / f"{backup_id}.json").write_text(json.dumps(metadata), encoding="utf-8")
        return metadata

    def test_backup_list_requires_superuser(self):
        self.client.force_login(self.staff)
        response = self.client.get("/api/settings/backups/")
        self.assertEqual(response.status_code, 403)

        self.client.force_login(self.superuser)
        response = self.client.get("/api/settings/backups/")
        self.assertEqual(response.status_code, 200)

    def test_completed_backup_is_listed_and_downloadable(self):
        item = self.write_backup()
        self.client.force_login(self.superuser)
        response = self.client.get("/api/settings/backups/")
        self.assertEqual(response.status_code, 200)
        row = response.json()["rows"][0]
        self.assertEqual(row["id"], item["id"])
        self.assertTrue(row["download_available"])
        self.assertIn(item["id"], row["restore_command"])

        response = self.client.get(f"/api/settings/backups/{item['id']}/download/")
        self.assertEqual(response.status_code, 200)
        self.assertIn("attachment", response["Content-Disposition"])
        self.assertEqual(b"".join(response.streaming_content), b"synthetic bundle")

    def test_create_backup_uses_internal_agent(self):
        self.client.force_login(self.superuser)
        with patch("core.api_views.create_backup", return_value={"backup_id": "job-1", "status": "starting"}) as create:
            response = self.client.post("/api/settings/backups/create/")
        self.assertEqual(response.status_code, 202)
        self.assertEqual(response.json()["backup"]["backup_id"], "job-1")
        create.assert_called_once_with()

    def test_delete_removes_bundle_and_metadata(self):
        item = self.write_backup()
        self.client.force_login(self.superuser)
        response = self.client.delete(f"/api/settings/backups/{item['id']}/")
        self.assertEqual(response.status_code, 200)
        self.assertFalse((Path(self.directory.name) / f"{item['id']}.mvbackup").exists())
        self.assertFalse((Path(self.directory.name) / f"{item['id']}.json").exists())


    def test_stale_running_metadata_is_reported_as_interrupted(self):
        self.write_backup(backup_id="stale-backup", status="running", verified=False)
        self.client.force_login(self.superuser)

        response = self.client.get("/api/settings/backups/")
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertFalse(payload["running"])
        row = next(item for item in payload["rows"] if item["id"] == "stale-backup")
        self.assertEqual(row["status"], "interrupted")
        self.assertFalse(row["verified"])
        self.assertFalse(row["download_available"])
        self.assertIn("not a usable recovery bundle", row["error"])

    def test_maintenance_lock_blocks_writes_but_not_reads(self):
        self.client.force_login(self.superuser)
        (Path(self.directory.name) / ".maintenance-lock").write_text("{}", encoding="utf-8")

        response = self.client.get("/api/settings/backups/")
        self.assertEqual(response.status_code, 200)

        response = self.client.post("/api/settings/backups/create/")
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()["code"], "backup_in_progress")
