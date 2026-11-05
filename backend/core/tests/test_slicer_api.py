"""Slicer drafts are private, inert, and never trigger printer actions."""
import json
import uuid

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.test import TestCase

from core.models import FileAsset, Printer, SliceJob


class SliceJobApiTests(TestCase):
    def setUp(self):
        user_model = get_user_model()
        self.owner = user_model.objects.create_user(username="slicer-owner", password="test-password")
        self.other = user_model.objects.create_user(username="slicer-other", password="test-password")
        permission = Permission.objects.get(codename="add_fileasset")
        self.owner.user_permissions.add(permission)
        self.printer = Printer.objects.create(owner=self.owner, name="Test printer", model="Test FDM")
        self.input_asset = FileAsset.objects.create(
            owner=self.owner, name="part.stl", category="mesh"
        )
        self.url = "/api/printing/slicer/jobs/"
        self.payload = {
            "input_asset_id": str(self.input_asset.pk),
            "printer_id": str(self.printer.pk),
            "engine": "prusaslicer",
            "engine_version": "2.9.4",
            "printer_preset": "Generic FDM",
            "filament_preset": "Generic PLA",
            "process_preset": "0.20mm Quality",
            "nozzle_mm": "0.4",
        }

    def post(self, data=None):
        return self.client.post(
            self.url, data=json.dumps(self.payload if data is None else data),
            content_type="application/json",
        )

    def test_inert_draft_lifecycle_and_engine_catalogue(self):
        self.client.force_login(self.owner)
        engines = self.client.get("/api/printing/slicer/engines/")
        self.assertEqual(engines.status_code, 200)
        self.assertFalse(engines.json()["worker_configured"])
        self.assertFalse(engines.json()["engines"][0]["available"])
        created = self.post()
        self.assertEqual(created.status_code, 201, created.content)
        job = SliceJob.objects.get(id=created.json()["job"]["id"])
        self.assertEqual(job.status, "draft")
        self.assertEqual(job.progress, 0)
        self.assertIsNone(job.output_asset_id)
        self.assertEqual(self.client.get(self.url).json()["jobs"][0]["id"], str(job.pk))
        detail = self.client.get(f"{self.url}{job.pk}/")
        self.assertEqual(detail.status_code, 200)
        self.assertFalse(detail.json()["execution_available"])

    def test_drafts_are_owner_scoped_even_when_id_known(self):
        self.client.force_login(self.owner)
        created = self.post()
        job_id = created.json()["job"]["id"]
        self.client.force_login(self.other)
        self.assertEqual(self.client.get(self.url).json()["jobs"], [])
        self.assertEqual(self.client.get(f"{self.url}{job_id}/").status_code, 404)
        self.assertEqual(self.client.delete(f"{self.url}{job_id}/").status_code, 404)
        self.assertEqual(self.post().status_code, 403)

    def test_cross_owner_assets_and_printer_are_rejected(self):
        alien = FileAsset.objects.create(owner=self.other, name="private.stl", category="mesh")
        self.client.force_login(self.owner)
        self.assertEqual(self.post({**self.payload, "input_asset_id": str(alien.pk)}).status_code, 400)
        self.assertEqual(SliceJob.objects.count(), 0)
        self.assertEqual(self.post({**self.payload, "printer_id": str(uuid.uuid4())}).status_code, 400)

    def test_rejects_untrusted_execution_fields_and_profile_paths(self):
        self.client.force_login(self.owner)
        for patch in (
            {"command": "rm -rf /"},
            {"settings": {"shell": "true"}},
            {"printer_preset": "../root/profile.ini"},
            {"filament_preset": "--export-gcode"},
            {"engine": "/usr/bin/python"},
            {"input_asset_id": "not-a-uuid"},
            {"nozzle_mm": "NaN"},
            {"nozzle_mm": "999"},
        ):
            with self.subTest(patch=patch):
                self.assertEqual(self.post({**self.payload, **patch}).status_code, 400)
        self.assertEqual(SliceJob.objects.count(), 0)

    def test_unscheduled_draft_delete_requires_permission(self):
        self.client.force_login(self.owner)
        job_id = self.post().json()["job"]["id"]
        self.assertEqual(self.client.delete(f"{self.url}{job_id}/").status_code, 403)
        self.owner.user_permissions.add(Permission.objects.get(codename="delete_slicejob"))
        # Re-fetch auth session permissions after grant.
        self.client.force_login(self.owner)
        self.assertEqual(self.client.delete(f"{self.url}{job_id}/").status_code, 200)
        self.assertFalse(SliceJob.objects.filter(pk=job_id).exists())
