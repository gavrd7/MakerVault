from datetime import timedelta
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from core.models import FileAsset, Printer, SliceJob
from core.slicer_execution import reconcile_stale_jobs, process_queued_job


class SliceJobRecoveryTests(TestCase):
    def setUp(self):
        user = get_user_model().objects.create_user(username="recovery-owner", password="unused")
        self.asset = FileAsset.objects.create(owner=user, name="test.stl", category="mesh")
        self.printer = Printer.objects.create(owner=user, name="Test", model="Generic")
        self.owner = user

    def create_job(self, status, minutes):
        job = SliceJob.objects.create(
            owner=self.owner, input_asset=self.asset, printer=self.printer,
            engine="orcaslicer", engine_version="test", nozzle_mm="0.40",
            printer_preset="machine", filament_preset="material", process_preset="process",
            status=status,
        )
        SliceJob.objects.filter(pk=job.pk).update(
            updated_at=timezone.now() - timedelta(minutes=minutes),
        )
        job.refresh_from_db()
        return job

    def test_overdue_only_becomes_stale_without_requeue_or_print(self):
        queued = self.create_job("queued", 45)
        active = self.create_job("running", 10)
        abandoned = self.create_job("running", 30)
        draft = self.create_job("draft", 60)
        result = reconcile_stale_jobs()
        self.assertEqual(result, {"queued": 1, "running": 1})
        for job, expected in (
            (queued, "stale"), (active, "running"),
            (abandoned, "stale"), (draft, "draft"),
        ):
            job.refresh_from_db()
            self.assertEqual(job.status, expected)
        self.assertEqual(process_queued_job(queued.pk)["status"], "skipped")
        self.assertEqual(reconcile_stale_jobs(), {"queued": 0, "running": 0})

    def test_reconciliation_limit_is_validated(self):
        from core.slicer_execution import SlicerExecutionError
        for invalid in (0, -1, 1001, None):
            with self.subTest(value=invalid), self.assertRaises(SlicerExecutionError):
                reconcile_stale_jobs(limit=invalid)
