from unittest.mock import patch

from django.test import TestCase

from core import tasks


class BackupTaskPauseTests(TestCase):
    def test_periodic_schedulers_do_not_mutate_or_queue_during_backup(self):
        with patch("core.tasks.backup_in_progress", return_value=True):
            self.assertEqual(
                tasks.catalogue_maintenance_tick.run(),
                {"status": "backup-in-progress", "queued": []},
            )
            self.assertEqual(
                tasks.printing_integrations_tick.run(),
                {"status": "backup-in-progress", "queued": []},
            )
            self.assertEqual(
                tasks.live_printer_connections_tick.run(),
                {"status": "backup-in-progress", "queued": [], "count": 0},
            )

    def test_direct_background_jobs_defer_during_backup(self):
        with patch("core.tasks.backup_in_progress", return_value=True):
            self.assertEqual(
                tasks.printing_integration_sync_task.run("setting-1"),
                {"status": "backup-in-progress", "setting_id": "setting-1"},
            )
            self.assertEqual(
                tasks.live_printer_connection_poll_task.run("connection-1"),
                {"status": "backup-in-progress", "connection_id": "connection-1"},
            )

    def test_manual_catalogue_queue_does_not_create_settings_row_during_backup(self):
        self.assertFalse(tasks.CatalogueMaintenanceSettings.objects.exists())
        with patch("core.tasks.backup_in_progress", return_value=True):
            config, queued = tasks.queue_catalogue_maintenance_now(triggered_by="test")
        self.assertEqual(queued, [])
        self.assertFalse(tasks.CatalogueMaintenanceSettings.objects.exists())
        self.assertEqual(config.singleton_key, 1)
