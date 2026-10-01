import tempfile
from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, SimpleTestCase, override_settings

from core.api_views import _printing_analytics, _serialise_print_job
from core.models import FileAsset, Printer, PrintJob, PrintMaterialUsage
from core.print_material_reporting import parse_gcode_weight, capture_material, material_summary
from core.printer_connectivity import poll_moonraker


class GcodeWeightParserTests(SimpleTestCase):
    def test_multitool_and_repeated_headers_are_not_double_counted(self):
        report = parse_gcode_weight("; filament used [g] = 1.25, 0, 2.50\n; filament used [g] = 1.25, 0, 2.50")
        self.assertEqual(report["used_g"], 3.75)
        self.assertTrue(report["estimated"])

    def test_explicit_total_and_zero(self):
        self.assertEqual(parse_gcode_weight("; total filament weight [g] : 0")["used_g"], 0)
        self.assertEqual(parse_gcode_weight("; filament used [g] = 1,2\n; total filament used [g] = 3")["used_g"], 3)

    def test_unknown_length_invalid_and_conflicting_values_remain_missing(self):
        for text in (";Filament used: 12 m", "; filament used [g] = -1", "; filament used [g] = NaN", "; filament used [g] = 1\n; filament used [g] = 2", "; filament used [g] = 100001"):
            self.assertIsNone(parse_gcode_weight(text))

    @patch("core.printer_connectivity._get")
    def test_moonraker_length_conversion_is_labelled_estimated(self, get):
        get.side_effect = [{"result": {}}, {"result": {"status": {"print_stats": {"filename": "folder/a b.gcode", "state": "printing", "filament_used": 500}}}}, {"result": {"filament_weight_total": 10, "filament_total": 1000}}]
        snapshot = poll_moonraker("http://printer.local")
        self.assertEqual(snapshot["job"]["filament_used_g"], 5)
        self.assertTrue(snapshot["job"]["filament_usage_estimated"])
        self.assertIn("filename=folder%2Fa%20b.gcode", get.call_args.args[0])


class AutomaticMaterialUsageTests(TestCase):
    def setUp(self):
        self.owner = get_user_model().objects.create_superuser("material-owner", "materials@example.com", "test-pass")
        self.printer = Printer.objects.create(owner=self.owner, name="K2")
        self.job = PrintJob.objects.create(owner=self.owner, printer=self.printer, status="success", settings={"live_monitor": {"filename": "part.gcode", "source": "live_printer"}})
        self.client.force_login(self.owner)

    def test_printer_report_replaces_estimate_and_manual_rows_win(self):
        self.job.settings["automatic_material_usage"] = {"used_g": 10, "source": "uploaded_gcode", "estimated": True}
        self.job.save()
        snapshot = {"adapter": "test", "job": {"file_name": "part.gcode", "filament_used_g": 7.5}}
        capture_material(self.job, snapshot)
        capture_material(self.job, snapshot)
        self.assertEqual(material_summary(self.job)["used_g"], 7.5)
        self.assertFalse(material_summary(self.job)["estimated"])
        PrintMaterialUsage.objects.create(print_job=self.job, used_g=Decimal("6.25"))
        self.assertEqual(material_summary(self.job)["used_g"], 6.25)
        self.assertEqual(_printing_analytics(self.owner)["filament_used_g"], 6.25)

    def test_failed_print_never_counts_full_file_estimate(self):
        self.job.status = "failed"
        self.job.settings["automatic_material_usage"] = {"used_g": 10, "estimated": True, "source": "uploaded_gcode"}
        self.job.save()
        self.assertIsNone(material_summary(self.job)["used_g"])

    def test_partial_printer_estimate_survives_missing_final_reading(self):
        capture_material(self.job, {"job": {"filament_used_g": 2, "filament_usage_estimated": True, "filament_usage_basis": "extrusion_length"}})
        capture_material(self.job, {"job": {"filament_estimated_g": 10}})
        with patch("core.print_material_reporting.matching_gcode") as match:
            capture_material(self.job)
            match.assert_not_called()
        self.assertEqual(material_summary(self.job)["used_g"], 2)

    def test_partial_extrusion_estimate_and_filename_guard(self):
        self.job.status = "failed"
        self.job.save()
        capture_material(self.job, {"job": {"file_name": "other.gcode", "filament_used_g": 20}})
        self.assertIsNone(material_summary(self.job)["used_g"])
        capture_material(self.job, {"job": {"file_name": "part.gcode", "filament_used_g": 2, "filament_usage_estimated": True, "filament_usage_basis": "extrusion_length"}})
        self.assertEqual(material_summary(self.job)["used_g"], 2)
        self.assertEqual(_serialise_print_job(self.job)["filament_usage_source"], "printer_report")

    def test_upload_backfills_completed_job_without_spool_deduction(self):
        with tempfile.TemporaryDirectory() as folder, override_settings(MEDIA_ROOT=folder):
            response = self.client.post("/api/files/", {"category": "other", "file": SimpleUploadedFile("part.gcode", b"; filament used [g] = 4.25\nG1 X0")})
            self.assertEqual(response.status_code, 201, response.content)
            self.job.refresh_from_db()
            self.assertEqual(material_summary(self.job)["used_g"], 4.25)
            self.assertEqual(PrintMaterialUsage.objects.count(), 0)
            analytics = _printing_analytics(self.owner)
            self.assertEqual(analytics["estimated_usage_jobs"], 1)
            self.assertIsNone(analytics["waste_g"])

    def test_owner_scope_and_ambiguous_filename_do_not_match(self):
        other = get_user_model().objects.create_user("other-material-owner")
        FileAsset.objects.create(owner=other, name="part.gcode", metadata={"original_name": "part.gcode"})
        capture_material(self.job)
        self.assertIsNone(material_summary(self.job)["used_g"])
        for _ in range(2):
            FileAsset.objects.create(owner=self.owner, name="part.gcode", metadata={"original_name": "part.gcode"})
        capture_material(self.job)
        self.assertIsNone(material_summary(self.job)["used_g"])
