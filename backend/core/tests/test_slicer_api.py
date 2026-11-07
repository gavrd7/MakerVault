"""Slicer drafts are private, inert, and never trigger printer actions."""
import json
import uuid

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.test import TestCase

from core.models import FileAsset, Printer, SliceJob, SlicerProfile


class SliceJobApiTests(TestCase):
    def setUp(self):
        user_model = get_user_model()
        self.owner = user_model.objects.create_user(username="slicer-owner", password="test-password")
        self.other = user_model.objects.create_user(username="slicer-other", password="test-password")
        permission = Permission.objects.get(codename="add_fileasset")
        self.owner.user_permissions.add(permission)
        self.printer = Printer.objects.create(owner=self.owner, name="Test printer", model="Test FDM")
        self.input_asset = FileAsset.objects.create(
            owner=self.owner, name="Printable Part", category="mesh",
            metadata={"extension": ".stl", "original_name": "part.stl"}
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

    def test_customise_creality_profile_in_gui_preserves_original(self):
        from django.core.files.base import ContentFile
        import hashlib
        original = b'{"name":"Original PLA","nozzle_temperature":["210"],"bed_temperature":["60"]}'
        asset = FileAsset(owner=self.owner, name="Original PLA.json", category="source",
                          metadata={"extension": ".json", "original_name": "Original PLA.json"})
        asset.file = ContentFile(original, name="creality-test-original.json")
        asset.save()
        profile = SlicerProfile.objects.create(
            owner=self.owner, file_asset=asset, engine="crealityprint",
            engine_version="7.3.0", kind="filament", name="Original PLA",
            content_sha256=hashlib.sha256(original).hexdigest(),
            status="candidate",
        )
        url = f"/api/printing/slicer/profiles/{profile.pk}/customise/"
        self.client.force_login(self.other)
        self.assertEqual(self.client.get(url).status_code, 404)
        self.client.force_login(self.owner)
        inspected = self.client.get(url)
        self.assertEqual(inspected.status_code, 200, inspected.content)
        self.assertEqual(inspected.json()["settings"]["nozzle_temperature"]["current"], 210)
        response = self.client.post(url, data=json.dumps({
            "name": "Custom PLA 220", "settings": {"nozzle_temperature": 220},
        }), content_type="application/json")
        self.assertEqual(response.status_code, 201, response.content)
        custom = SlicerProfile.objects.get(pk=response.json()["profile"]["id"])
        self.assertEqual(custom.engine, "crealityprint")
        self.assertEqual(custom.status, "candidate")
        self.assertNotEqual(custom.file_asset_id, profile.file_asset_id)
        with custom.file_asset.file.open("rb") as stream:
            self.assertEqual(json.load(stream)["nozzle_temperature"], ["220"])
        with asset.file.open("rb") as stream:
            self.assertEqual(stream.read(), original)
        self.assertEqual(self.client.post(url, data=json.dumps({
            "name": "Unsafe", "settings": {"post_process": 1},
        }), content_type="application/json").status_code, 400)

    def test_preview_is_admin_only_and_never_reports_worker_installed(self):
        from unittest.mock import patch
        url = "/api/printing/slicer/engines/"
        with patch.dict("os.environ", {
            "MAKERVAULT_SLICER_PREVIEW_ENABLED": "1",
            "MAKERVAULT_SLICER_EXECUTION_ENABLED": "0",
        }):
            self.client.force_login(self.owner)
            result = self.client.get(url)
            self.assertFalse(result.json()["preview_enabled"])
            self.assertFalse(result.json()["worker_configured"])
            self.owner.is_superuser = True
            self.owner.save(update_fields=["is_superuser"])
            result = self.client.get(url)
            self.assertTrue(result.json()["preview_enabled"])
            self.assertFalse(result.json()["worker_configured"])
            self.assertFalse(result.json()["deployment_enabled"])

    def test_optional_slicer_deployment_reports_absent_or_unavailable(self):
        from unittest.mock import patch

        self.client.force_login(self.owner)
        url = "/api/printing/slicer/engines/"
        with patch.dict("os.environ", {"MAKERVAULT_SLICER_EXECUTION_ENABLED": "0"}):
            response = self.client.get(url)
            self.assertEqual(response.status_code, 200)
            self.assertFalse(response.json()["deployment_enabled"])
            self.assertFalse(response.json()["worker_configured"])

        # Execution enabled is not evidence of an installed or approved worker.
        with patch.dict("os.environ", {"MAKERVAULT_SLICER_EXECUTION_ENABLED": "1"}):
            with patch("core.slicer_api.verified_installation", return_value={}):
                response = self.client.get(url)
                self.assertTrue(response.json()["deployment_enabled"])
                self.assertFalse(response.json()["worker_configured"])

        with patch.dict("os.environ", {"MAKERVAULT_SLICER_EXECUTION_ENABLED": "1"}):
            with patch("core.slicer_api.verified_installation", return_value={
                "orcaslicer": {"version": "2.4.2", "enabled": True, "verified": True}
            }):
                response = self.client.get(url)
                self.assertTrue(response.json()["deployment_enabled"])
                self.assertTrue(response.json()["worker_configured"])

    def test_read_only_mesh_inspection_requires_ownership_and_valid_stl(self):
        from django.core.files.base import ContentFile
        stl = (b"solid sample\nfacet normal 0 0 1\nouter loop\n"
               b"vertex 0 0 0\nvertex 10 0 0\nvertex 0 10 2\n"
               b"endloop\nendfacet\nendsolid sample\n")
        self.input_asset.file = ContentFile(stl, name="part.stl")
        self.input_asset.save(update_fields=["file"])
        self.client.force_login(self.owner)
        url = f"/api/printing/slicer/meshes/{self.input_asset.pk}/inspection/"
        result = self.client.get(url)
        self.assertEqual(result.status_code, 200, result.content)
        self.assertEqual(result.json()["mesh"]["size_mm"], [10, 10, 2])
        self.assertEqual(result.json()["mesh"]["printer_fit"], "not_checked")
        self.client.force_login(self.other)
        self.assertEqual(self.client.get(url).status_code, 404)
        self.client.force_login(self.owner)
        self.input_asset.file.save("part.stl", ContentFile(b"not an STL"), save=True)
        self.assertEqual(self.client.get(url).status_code, 422)

    def test_visual_multi_stl_plate_is_saved_but_never_slicable(self):
        from core.slicer_execution import SlicerExecutionError, validate_scheduling
        self.client.force_login(self.owner)
        second = FileAsset.objects.create(
            owner=self.owner, name="second.stl", category="mesh",
            metadata={"extension": ".stl", "original_name": "second.stl"},
        )
        instances = [
            {"instance_id": str(uuid.uuid4()), "asset_id": str(self.input_asset.pk),
             "x_mm": 0, "y_mm": 0, "rotation_deg": 0, "scale_percent": 100,
             "color": "#58b5e4"},
            {"instance_id": str(uuid.uuid4()), "asset_id": str(second.pk),
             "x_mm": 25, "y_mm": 30, "rotation_deg": 90, "scale_percent": 80,
             "color": "#f59e0b"},
        ]
        result = self.post({**self.payload, "settings": {"plate_objects": instances}})
        self.assertEqual(result.status_code, 201, result.content)
        row = SliceJob.objects.get(pk=result.json()["job"]["id"])
        self.assertEqual(len(row.settings["plate_objects"]), 2)
        self.assertEqual(row.settings["plate_objects"][1]["rotation_deg"], 90.0)
        self.assertFalse(result.json()["job"]["can_slice"])
        with self.assertRaisesRegex(SlicerExecutionError, "multi-object slicing"):
            validate_scheduling(row, {"prusaslicer": {"enabled": True, "verified": True}})
        self.assertEqual(self.client.post(f"{self.url}{row.pk}/start/").status_code, 409)

    def test_visual_plate_rejects_foreign_files_and_untrusted_settings(self):
        self.client.force_login(self.owner)
        foreign = FileAsset.objects.create(
            owner=self.other, name="not-yours.stl", category="mesh",
            metadata={"extension": ".stl"},
        )
        valid = {"instance_id": str(uuid.uuid4()), "asset_id": str(self.input_asset.pk),
                 "x_mm": 0, "y_mm": 0, "rotation_deg": 0, "scale_percent": 100,
                 "color": "#58b5e4"}
        for obj in (
            {**valid, "asset_id": str(foreign.pk)},
            {**valid, "x_mm": float("inf")},
            {**valid, "scale_percent": 0},
            {**valid, "color": "#red"},
            {**valid, "script": "M112"},
        ):
            with self.subTest(instance=obj):
                response = self.post({**self.payload, "settings": {"plate_objects": [obj]}})
                self.assertEqual(response.status_code, 400, response.content)
        self.assertEqual(SliceJob.objects.count(), 0)

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

    def test_stl_extension_is_taken_from_metadata_not_display_title(self):
        self.client.force_login(self.owner)
        self.assertEqual(self.post().status_code, 201)
        self.input_asset.metadata = {"extension": ".3mf", "original_name": "part.3mf"}
        self.input_asset.save(update_fields=["metadata"])
        self.assertEqual(self.post().status_code, 400)

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

    def test_native_profile_selection_requires_matching_ownership_version_and_kind(self):
        source = FileAsset.objects.create(
            owner=self.owner, name="Saved native profiles", category="source",
            metadata={"extension": ".ini"},
        )
        profiles = {}
        for kind, label in (
            ("printer", "Generic FDM"),
            ("filament", "Generic PLA"),
            ("process", "0.20mm Quality"),
        ):
            profiles[kind] = SlicerProfile.objects.create(
                owner=self.owner, engine="prusaslicer", engine_version="2.9.4",
                kind=kind, name=label, file_asset=source,
                content_sha256="b" * 64,
            )
        self.client.force_login(self.owner)
        linked = {
            **self.payload,
            **{kind + "_profile_id": str(profile.pk) for kind, profile in profiles.items()},
        }
        created = self.post(linked)
        self.assertEqual(created.status_code, 201, created.content)
        row = SliceJob.objects.get(pk=created.json()["job"]["id"])
        self.assertEqual(row.printer_profile_id, profiles["printer"].pk)
        self.assertEqual(row.filament_profile_id, profiles["filament"].pk)
        self.assertEqual(row.process_profile_id, profiles["process"].pk)
        self.assertEqual(row.status, "draft")
        self.assertEqual(self.post({**linked, "engine_version": "2.9.7"}).status_code, 400)
        self.assertEqual(self.post({**linked, "printer_preset": "Different label"}).status_code, 400)
        foreign_source = FileAsset.objects.create(owner=self.other, name="Other.ini", category="source")
        foreign = SlicerProfile.objects.create(
            owner=self.other, engine="prusaslicer", engine_version="2.9.4",
            kind="printer", name="Generic FDM", file_asset=foreign_source,
            content_sha256="c" * 64,
        )
        self.assertEqual(self.post({**linked, "printer_profile_id": str(foreign.pk)}).status_code, 400)

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

    def test_executable_start_fails_closed_without_approved_worker(self):
        self.client.force_login(self.owner)
        job_id = self.post().json()["job"]["id"]
        response = self.client.post(f"{self.url}{job_id}/start/", "{}", content_type="application/json")
        self.assertEqual(response.status_code, 409)
        self.assertEqual(SliceJob.objects.get(pk=job_id).status, "draft")

    def test_queued_job_fails_without_verified_worker_instead_of_sticking(self):
        from core.slicer_execution import process_queued_job
        from unittest.mock import patch
        self.client.force_login(self.owner)
        job_id = self.post().json()["job"]["id"]
        SliceJob.objects.filter(pk=job_id).update(status="queued")
        with patch("core.slicer_execution.verified_installation", return_value={}):
            result = process_queued_job(job_id)
        self.assertEqual(result["status"], "failed")
        self.assertEqual(SliceJob.objects.get(pk=job_id).status, "failed")

    def test_cancel_queued_job_does_not_run_or_change_printer(self):
        from core.slicer_execution import process_queued_job
        from core.models import PrinterGcodeSubmission
        self.client.force_login(self.owner)
        job_id = self.post().json()["job"]["id"]
        self.owner.user_permissions.add(Permission.objects.get(codename="change_slicejob"))
        self.client.force_login(self.owner)
        SliceJob.objects.filter(pk=job_id).update(status="queued")
        count = PrinterGcodeSubmission.objects.count()
        result = self.client.post(f"{self.url}{job_id}/cancel/", "{}", content_type="application/json")
        self.assertEqual(result.status_code, 200, result.content)
        self.assertEqual(result.json()["job"]["status"], "cancelled")
        self.assertEqual(process_queued_job(job_id)["status"], "skipped")
        self.assertEqual(PrinterGcodeSubmission.objects.count(), count)
        self.assertEqual(self.client.post(f"{self.url}{job_id}/start/").status_code, 409)

    def test_cannot_cancel_running_job_or_another_owners_job(self):
        self.client.force_login(self.owner)
        job_id = self.post().json()["job"]["id"]
        self.owner.user_permissions.add(Permission.objects.get(codename="change_slicejob"))
        self.client.force_login(self.owner)
        SliceJob.objects.filter(pk=job_id).update(status="running")
        self.assertEqual(self.client.post(f"{self.url}{job_id}/cancel/").status_code, 409)
        self.client.force_login(self.other)
        self.assertEqual(self.client.post(f"{self.url}{job_id}/cancel/").status_code, 404)

    def test_unscheduled_draft_delete_requires_permission(self):
        self.client.force_login(self.owner)
        job_id = self.post().json()["job"]["id"]
        self.assertEqual(self.client.delete(f"{self.url}{job_id}/").status_code, 403)
        self.owner.user_permissions.add(Permission.objects.get(codename="delete_slicejob"))
        # Re-fetch auth session permissions after grant.
        self.client.force_login(self.owner)
        self.assertEqual(self.client.delete(f"{self.url}{job_id}/").status_code, 200)
        self.assertFalse(SliceJob.objects.filter(pk=job_id).exists())
