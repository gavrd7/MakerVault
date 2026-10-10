from io import StringIO
from unittest.mock import patch

from django.core.management import call_command
from django.test import TestCase

from core.models import CatalogueMaintenanceSettings, ReusableSpoolCatalogEntry
from core.tasks import _queue_catalogue_maintenance


class ReusableSpoolMaintenanceTests(TestCase):
    def test_verified_source_check_tracks_status_not_specs(self):
        entry = ReusableSpoolCatalogEntry.objects.get(key="bambu-basic")
        original_tare = entry.nominal_tare_g
        original_limit = entry.max_dryer_temp_c
        with patch(
            "core.management.commands.refresh_reusable_spool_sources.fetch_catalogue_source_html",
            return_value=("<html><title>Reusable spool</title></html>", entry.source_url),
        ) as fetch:
            out = StringIO()
            call_command("refresh_reusable_spool_sources", key=entry.key, stdout=out)
        fetch.assert_called_once_with(entry.source_url)
        entry.refresh_from_db()
        self.assertEqual(entry.provenance["last_check_status"], "ok")
        self.assertTrue(entry.provenance["last_checked_at"])
        self.assertEqual(entry.nominal_tare_g, original_tare)
        self.assertEqual(entry.max_dryer_temp_c, original_limit)

    @patch("core.tasks.backup_in_progress", return_value=False)
    @patch("core.tasks.refresh_reusable_spool_sources_task.delay")
    def test_existing_maintenance_schedule_queues_spool_reference_check(self, delay, backup):
        config = CatalogueMaintenanceSettings(
            check_board_data=False, check_printer_data=False,
            check_filament_data=False, check_images=False,
            check_reusable_spool_sources=True,
        )
        queued = _queue_catalogue_maintenance(config)
        self.assertEqual(queued, ["reusable-spool-sources"])
        delay.assert_called_once_with(limit=5)


    def test_image_candidate_requires_matching_product_title(self):
        from core.reusable_spool_images import official_image_candidate
        entry = ReusableSpoolCatalogEntry.objects.get(key="bambu-basic")
        page = ('<html><head><meta property="og:title" '
                'content="Bambu Lab Reusable Spool Basic">'
                '<meta property="og:image" '
                'content="https://cdn.example.org/reusable-spool.webp"></head></html>')
        self.assertEqual(
            official_image_candidate(entry, page, entry.source_url),
            "https://cdn.example.org/reusable-spool.webp",
        )
        generic = ('<html><head><meta property="og:title" content="Home">'
                   '<meta property="og:image" content="https://cdn.example.org/logo.jpg"></head></html>')
        self.assertIsNone(official_image_candidate(entry, generic, entry.source_url))

    @patch("core.tasks.backup_in_progress", return_value=False)
    @patch("core.tasks.seed_catalogue_images_task.delay")
    @patch("core.tasks.refresh_reusable_spool_images_task.delay")
    def test_existing_image_schedule_includes_reusable_spool_images(self, spool_task, image_task, backup):
        config = CatalogueMaintenanceSettings(
            check_board_data=False, check_printer_data=False,
            check_filament_data=False, check_reusable_spool_sources=False,
            check_images=True,
        )
        queued = _queue_catalogue_maintenance(config)
        self.assertEqual(queued, ["images", "reusable-spool-images"])
        spool_task.assert_called_once_with(limit=3)
        image_task.assert_called_once_with(force_retry=True)
