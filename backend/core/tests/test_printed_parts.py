from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.test import TestCase, Client

from core.api_views import _printing_analytics
from core.live_print_jobs import sync_print_job_from_snapshot
from core.maker_tags import resolve_tag_target
from core.models import PrintedPart, PrintedPartEvent, Printer, PrinterConnection, PrintJob, Project, Model3D, ModelRevision
from core.user_admin import purge_user_private_data


class PrintedPartsTests(TestCase):
    def setUp(self):
        self.owner = get_user_model().objects.create_superuser("part-owner", "parts@example.com", "test-pass")
        self.other = get_user_model().objects.create_user("other-parts")
        self.printer = Printer.objects.create(owner=self.owner, name="K1")
        self.job = PrintJob.objects.create(owner=self.owner, printer=self.printer, status="success", quantity=2, settings={"live_monitor": {"filename": "untracked-model.gcode"}, "automatic_material_usage": {"used_g": 12.5, "source": "printer_report", "estimated": False}})
        self.client.force_login(self.owner)

    def create(self, **fields):
        return self.client.post("/api/printing/parts/", {"print_job_id": str(self.job.pk), "name": "Bracket", **fields}, content_type="application/json")

    def test_unlinked_live_print_accounts_filament_without_automatic_parts(self):
        connection = PrinterConnection.objects.create(printer=self.printer, adapter="moonraker")
        snapshot = {"state": "printing", "job": {"file_name": "temporary.gcode", "filament_used_g": 2}}
        result = sync_print_job_from_snapshot(connection, snapshot)
        snapshot["state"] = "complete"
        snapshot["job"]["filament_used_g"] = 3
        sync_print_job_from_snapshot(connection, snapshot)
        live = PrintJob.objects.get(pk=result["job_id"])
        self.assertEqual(live.status, "success")
        self.assertIsNone(live.model_revision_id)
        self.assertEqual(PrintedPart.objects.count(), 0)
        self.assertEqual(_printing_analytics(self.owner)["filament_used_g"], 15.5)

    def test_explicit_creation_does_not_change_filament_and_works_without_model(self):
        before = _printing_analytics(self.owner)
        response = self.create(quantity=2)
        self.assertEqual(response.status_code, 201, response.content)
        part = response.json()["part"]
        self.assertIsNone(part["model_revision_id"])
        self.assertEqual(part["production"]["filament_used_g"], 12.5)
        self.assertEqual(part["production"]["scope"], "whole_print_job")
        self.assertEqual(_printing_analytics(self.owner), before)
        self.assertEqual(PrintedPartEvent.objects.count(), 1)

    def test_repeated_request_cannot_overretain_print_quantity(self):
        self.assertEqual(self.create(quantity=2).status_code, 201)
        self.assertEqual(self.create(quantity=2).status_code, 400)
        self.assertEqual(PrintedPart.objects.count(), 1)

    def test_fractional_and_boolean_quantities_are_rejected(self):
        for value in (1.5, True, "1.5"):
            self.assertEqual(self.create(quantity=value).status_code, 400)
        self.assertFalse(PrintedPart.objects.exists())

    def test_failed_print_cannot_create_parts(self):
        self.job.status = "failed"
        self.job.save()
        self.assertEqual(self.create().status_code, 400)
        self.assertFalse(PrintedPart.objects.exists())

    def test_owner_boundaries_and_viewer_permissions(self):
        own = self.create().json()["part"]
        self.client.force_login(self.other)
        self.assertEqual(self.create().status_code, 403)
        self.assertEqual(self.client.get(f'/api/printing/parts/{own["id"]}/').status_code, 404)
        self.assertEqual(self.client.get('/api/printing/parts/').json()["rows"], [])
        self.other.user_permissions.add(Permission.objects.get(codename="add_printedpart"))
        self.assertEqual(self.create().status_code, 404)

    def test_installed_requires_owned_project_and_retirement_keeps_usage(self):
        other_project = Project.objects.create(owner=self.other, name="Private")
        self.assertEqual(self.create(status="installed", project_id=str(other_project.id)).status_code, 400)
        response = self.create(status="installed")
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["fields"]["project"], ["Choose the project where this part is installed."])
        project = Project.objects.create(owner=self.owner, name="Workshop")
        part = self.create(status="installed", project_id=str(project.pk)).json()["part"]
        response = self.client.patch(f'/api/printing/parts/{part["id"]}/', {"status": "scrapped"}, content_type="application/json")
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(len(response.json()["part"]["events"]), 2)
        self.assertEqual(_printing_analytics(self.owner)["filament_used_g"], 12.5)
        self.assertEqual(len(self.client.get(f'/api/printing/parts/?project_id={project.id}').json()["rows"]), 1)

    def test_print_quantity_correction_and_invalid_create_roll_back(self):
        response = self.create(quantity=3, print_job_quantity=3)
        self.assertEqual(response.status_code, 201, response.content)
        self.job.refresh_from_db()
        self.assertEqual(self.job.quantity, 3)
        self.assertEqual(_printing_analytics(self.owner)["filament_used_g"], 12.5)
        response = self.create(quantity=0, print_job_quantity=5)
        self.assertEqual(response.status_code, 400)
        self.job.refresh_from_db()
        self.assertEqual(self.job.quantity, 3)

    def test_delete_print_preserves_production_context_and_tag_target(self):
        part = self.create().json()["part"]
        target = resolve_tag_target(self.owner, "printed_part", part["id"])
        self.assertEqual(target.name, "Bracket")
        self.job.delete()
        response = self.client.get(f'/api/printing/parts/{part["id"]}/').json()["part"]
        self.assertIsNone(response["print_job_id"])
        self.assertEqual(response["production"]["printer"], "K1")
        self.assertEqual(response["production"]["filament_used_g"], 12.5)

    def test_csrf_and_account_purge(self):
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.owner)
        self.assertEqual(client.post("/api/printing/parts/", {"name": "Test"}).status_code, 403)
        self.create()
        purge_user_private_data(self.owner)
        self.assertFalse(PrintedPart.objects.exists())
        self.assertFalse(PrintedPartEvent.objects.exists())

    def test_manual_part_and_replacement_keep_original_history(self):
        first = self.create().json()["part"]
        response = self.client.post("/api/printing/parts/", {"name": "Replacement", "replaces_id": first["id"]}, content_type="application/json")
        self.assertEqual(response.status_code, 201, response.content)
        replacement = response.json()["part"]
        self.assertEqual(replacement["replaces_id"], first["id"])
        response = self.client.patch(f'/api/printing/parts/{first["id"]}/', {"replaces_id": first["id"]}, content_type="application/json")
        self.assertEqual(response.status_code, 400)
        self.assertEqual(PrintedPart.objects.count(), 2)
