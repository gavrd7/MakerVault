"""Bulk slicer cleanup preserves saved library G-code and source models."""
import json
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.test import TestCase

from core.models import FileAsset, Printer, SliceJob


class BulkSlicerCleanupTests(TestCase):
    def setUp(self):
        users = get_user_model()
        self.owner = users.objects.create_user(username="bulk-owner", password="unused")
        self.other = users.objects.create_user(username="bulk-other", password="unused")
        for user in (self.owner, self.other):
            user.user_permissions.add(Permission.objects.get(codename="add_fileasset"))
            user.user_permissions.add(Permission.objects.get(codename="delete_slicejob"))
        self.printer = Printer.objects.create(owner=self.owner, name="K2", model="Creality K2")
        self.mesh = FileAsset.objects.create(owner=self.owner, name="cube.stl",
            category="mesh", metadata={"extension": ".stl"})
        self.bulk = "/api/printing/slicer/jobs/bulk-delete/"
        self.clean = "/api/printing/slicer/jobs/remove-unsaved-gcode/"
        self.client.force_login(self.owner)

    def job(self, status="draft", owner=None):
        owner = owner or self.owner
        printer = self.printer if owner == self.owner else Printer.objects.create(
            owner=owner, name="Other printer", model="Generic")
        source = self.mesh if owner == self.owner else FileAsset.objects.create(
            owner=owner, name="other.stl", category="mesh", metadata={"extension": ".stl"})
        return SliceJob.objects.create(owner=owner, input_asset=source, printer=printer,
            engine="crealityprint", engine_version="7.3.1",
            printer_preset="K2", filament_preset="PLA", process_preset="0.20mm",
            nozzle_mm="0.4", status=status)

    def output(self, job, category="other", metadata=None):
        detail = {"generated_by": "makervault-slicer", "extension": ".gcode",
                  "slice_job_id": str(job.pk), "slicer_library_status": "pending"}
        detail.update(metadata or {})
        asset = FileAsset.objects.create(owner=self.owner, name="private.gcode",
            category=category, file="files/private-output.gcode", metadata=detail)
        job.output_asset = asset
        job.save(update_fields=["output_asset"])
        return asset

    def send(self, url, data):
        return self.client.post(url, data=json.dumps(data), content_type="application/json")

    def test_remove_all_drafts_only_and_preserve_sources(self):
        old = [self.job() for _ in range(3)]
        done = self.job("completed")
        other = self.job(owner=self.other)
        result = self.send(self.bulk, {"mode": "drafts", "ids": None})
        self.assertEqual(result.status_code, 200, result.content)
        self.assertEqual(result.json()["deleted"], 3)
        self.assertFalse(SliceJob.objects.filter(pk__in=[j.pk for j in old]).exists())
        self.assertTrue(SliceJob.objects.filter(pk=done.pk).exists())
        self.assertTrue(SliceJob.objects.filter(pk=other.pk).exists())
        self.assertTrue(FileAsset.objects.filter(pk=self.mesh.pk).exists())

    def test_remove_all_completed_slices_preserves_all_gcode(self):
        done = self.job("completed")
        private = self.output(done)
        draft = self.job()
        saved = self.job("completed")
        library = self.output(saved, category="gcode")
        result = self.send(self.bulk, {"mode": "slices", "ids": None})
        self.assertEqual(result.status_code, 200, result.content)
        self.assertEqual(result.json()["deleted"], 2)
        self.assertTrue(SliceJob.objects.filter(pk=draft.pk).exists())
        self.assertTrue(FileAsset.objects.filter(pk__in=[private.pk, library.pk]).count() == 2)

    def test_selected_is_atomic_and_active_job_is_never_deleted(self):
        draft = self.job()
        active = self.job("running")
        result = self.send(self.bulk, {
            "mode": "selected", "ids": [str(draft.pk), str(active.pk)]})
        self.assertEqual(result.status_code, 409, result.content)
        self.assertTrue(SliceJob.objects.filter(pk=draft.pk).exists())
        self.assertTrue(SliceJob.objects.filter(pk=active.pk).exists())
        missing = self.send(self.bulk, {
            "mode": "selected", "ids": [str(draft.pk), str(self.job(owner=self.other).pk)]})
        self.assertEqual(missing.status_code, 409, missing.content)
        self.assertTrue(SliceJob.objects.filter(pk=draft.pk).exists())

    def test_unsaved_private_gcode_only_and_preserve_history(self):
        done = self.job("completed")
        private = self.output(done)
        saved = self.job("completed")
        library = self.output(saved, category="gcode",
            metadata={"slicer_library_status": "saved"})
        bad = self.job("completed")
        malformed = self.output(bad, metadata={"slice_job_id": "not-the-job"})
        with patch("core.slicer_job_bulk.transaction.on_commit") as on_commit:
            result = self.send(self.clean, {})
        self.assertEqual(result.status_code, 200, result.content)
        self.assertEqual(result.json()["removed"], 1)
        self.assertFalse(FileAsset.objects.filter(pk=private.pk).exists())
        self.assertTrue(FileAsset.objects.filter(pk__in=[library.pk, malformed.pk]).count() == 2)
        done.refresh_from_db()
        saved.refresh_from_db()
        self.assertEqual(done.status, "stale")
        self.assertIsNone(done.output_asset_id)
        self.assertEqual(saved.status, "completed")
        self.assertEqual(saved.output_asset_id, library.pk)
        self.assertTrue(on_commit.called)

    def test_thumbnail_parser_uses_embedded_png_and_rejects_invalid_blocks(self):
        import base64
        from core.slicer_job_bulk import _embedded_thumbnail
        png = b"\x89PNG\r\n\x1a\n" + b"dummy"
        data = base64.b64encode(png)
        header = (b"; HEADER_BLOCK_START\n"
            + b"; thumbnail begin 96x96 " + str(len(data)).encode() + b"\n"
            + b"; " + data + b"\n; thumbnail end\n; HEADER_BLOCK_END\n")
        self.assertEqual(_embedded_thumbnail(header), png)
        self.assertIsNone(_embedded_thumbnail(header.replace(b"; thumbnail end", b"; bad end")))
        self.assertIsNone(_embedded_thumbnail(header.replace(
            str(len(data)).encode(), b"999", 1)))
        self.assertIsNone(_embedded_thumbnail(b"; thumbnail begin 96x96 500001\n"))

    def test_thumbnail_url_is_private_and_serves_existing_embedded_png(self):
        import base64
        from django.core.files.base import ContentFile
        job = self.job("completed")
        png = b"\x89PNG\r\n\x1a\n" + b"generated-thumbnail"
        encoded = base64.b64encode(png)
        gcode = (b"; thumbnail begin 96x96 " + str(len(encoded)).encode()
            + b"\n; " + encoded + b"\n; thumbnail end\nG1 X0 Y1\n")
        asset = FileAsset(owner=self.owner, name="slice.gcode", category="other",
            metadata={"generated_by": "makervault-slicer", "extension": ".gcode",
                      "slice_job_id": str(job.pk)})
        asset.file.save("slicer-thumbnail-test.gcode", ContentFile(gcode), save=False)
        asset.save()
        self.addCleanup(lambda item=asset: item.file.delete(save=False))
        job.output_asset = asset
        job.save(update_fields=["output_asset"])
        url = "/api/printing/slicer/jobs/" + str(job.pk) + "/thumbnail/"
        image = self.client.get(url)
        self.assertEqual(image.status_code, 200, image.content)
        self.assertEqual(image["Content-Type"], "image/png")
        self.assertEqual(image.content, png)
        self.client.force_login(self.other)
        self.assertEqual(self.client.get(url).status_code, 404)

    def test_bulk_methods_enforce_permission_and_scope(self):
        draft = self.job()
        self.client.force_login(self.other)
        result = self.send(self.bulk, {"mode": "selected", "ids": [str(draft.pk)]})
        self.assertEqual(result.status_code, 409)
        self.assertTrue(SliceJob.objects.filter(pk=draft.pk).exists())
        user = get_user_model().objects.create_user(username="no-bulk-perm")
        self.client.force_login(user)
        self.assertEqual(self.send(self.bulk, {"mode": "drafts", "ids": None}).status_code, 403)
        self.assertEqual(self.send(self.clean, {}).status_code, 403)
