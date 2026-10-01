from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase

from core.api_views import _printing_analytics, _serialise_print_job
from core.models import Printer, PrintJob, PrintMaterialUsage


class PrintUsageReportingTests(TestCase):
    def setUp(self):
        self.owner = get_user_model().objects.create_user("usage-owner")
        self.printer = Printer.objects.create(owner=self.owner, name="K2")

    def job(self, **kwargs):
        return PrintJob.objects.create(owner=self.owner, printer=self.printer, status="success", **kwargs)

    def test_empty_history_has_unknown_usage(self):
        analytics = _printing_analytics(self.owner)
        self.assertIsNone(analytics["filament_used_g"])
        self.assertIsNone(analytics["waste_g"])
        self.assertEqual(analytics["jobs_without_material_usage"], 0)

    def test_completed_live_job_with_duration_does_not_imply_material_usage(self):
        job = self.job(actual_minutes=10, settings={"live_monitor": {"source": "live_printer"}})
        analytics = _printing_analytics(self.owner)
        self.assertEqual(analytics["actual_minutes"], 10)
        self.assertIsNone(analytics["filament_used_g"])
        self.assertIsNone(analytics["waste_g"])
        self.assertEqual(analytics["jobs_without_material_usage"], 1)
        self.assertIsNone(_serialise_print_job(job)["filament_used_g"])
        self.assertIsNone(_serialise_print_job(job)["waste_g"])

    def test_recorded_zero_is_distinct_from_missing(self):
        job = self.job()
        PrintMaterialUsage.objects.create(print_job=job, used_g=0, waste_g=0)
        analytics = _printing_analytics(self.owner)
        self.assertEqual(analytics["filament_used_g"], 0)
        self.assertEqual(analytics["waste_g"], 0)
        self.assertEqual(analytics["jobs_with_material_usage"], 1)
        self.assertEqual(analytics["jobs_without_material_usage"], 0)
        self.assertEqual(_serialise_print_job(job)["filament_used_g"], 0)

    def test_partial_totals_count_prints_not_material_rows(self):
        recorded = self.job()
        self.job()
        PrintMaterialUsage.objects.create(print_job=recorded, used_g=Decimal("0.25"), waste_g=0)
        PrintMaterialUsage.objects.create(print_job=recorded, used_g=Decimal("2.50"), waste_g=Decimal("0.10"))
        analytics = _printing_analytics(self.owner)
        self.assertEqual(analytics["filament_used_g"], 2.75)
        self.assertEqual(analytics["waste_g"], 0.1)
        self.assertEqual(analytics["jobs_with_material_usage"], 1)
        self.assertEqual(analytics["jobs_without_material_usage"], 1)

    def test_other_owners_usage_does_not_fill_missing_total(self):
        self.job()
        other = get_user_model().objects.create_user("usage-other")
        printer = Printer.objects.create(owner=other, name="Other")
        job = PrintJob.objects.create(owner=other, printer=printer)
        PrintMaterialUsage.objects.create(print_job=job, used_g=100)
        analytics = _printing_analytics(self.owner)
        self.assertIsNone(analytics["filament_used_g"])
        self.assertEqual(analytics["jobs_with_material_usage"], 0)
