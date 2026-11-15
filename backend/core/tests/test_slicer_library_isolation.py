"""Private slicer assets must never leak into general Files/printing libraries."""
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.test import TestCase

from core.models import FileAsset, Printer, SliceJob, SlicerProfile
from core.slicer_output import store_generated_gcode


class SlicerLibraryIsolationTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="private-slicer-library", password="test"
        )
        self.user.user_permissions.add(Permission.objects.get(codename="add_fileasset"))
        self.client.force_login(self.user)
        self.source = FileAsset.objects.create(
            owner=self.user, category="mesh", name="part.stl",
            metadata={"extension": ".stl", "original_name": "part.stl"},
        )
        self.printer = Printer.objects.create(
            owner=self.user, name="Test machine", model="Generic",
        )

    def library_ids(self):
        response = self.client.get("/api/files/")
        self.assertEqual(response.status_code, 200, response.content)
        return {item["id"] for item in response.json()["rows"]}

    def printing_ids(self, key):
        response = self.client.get("/api/printing/")
        self.assertEqual(response.status_code, 200, response.content)
        return {item["id"] for item in response.json()[key]}

    def job(self, save=False):
        return SliceJob.objects.create(
            owner=self.user, input_asset=self.source, printer=self.printer,
            engine="prusaslicer", engine_version="2.9.7",
            printer_preset="Generic", filament_preset="PLA", process_preset="Normal",
            nozzle_mm="0.40", status="running",
            settings={"save_gcode_to_library": save},
        )

    def test_private_gcode_is_in_job_not_files_or_printing_library(self):
        job = self.job()
        output = store_generated_gcode(job.pk, b"; generated\nG1 X1 Y1 E0.5\n")
        self.assertEqual(output.category, "other")
        self.assertNotIn(str(output.pk), self.library_ids())
        self.assertNotIn(str(output.pk), self.printing_ids("gcode_files"))
        self.assertNotIn(str(output.pk), self.printing_ids("model_files"))
        job.refresh_from_db()
        self.assertEqual(job.output_asset_id, output.pk)
        self.assertTrue(FileAsset.objects.filter(pk=output.pk).exists())

        saved = self.client.post(
            f"/api/printing/slicer/jobs/{job.pk}/save-gcode/",
            data="{}", content_type="application/json",
        )
        self.assertEqual(saved.status_code, 200, saved.content)
        self.assertIn(str(output.pk), self.library_ids())
        self.assertIn(str(output.pk), self.printing_ids("gcode_files"))

    def test_opt_in_gcode_and_regular_user_source_are_visible(self):
        output = store_generated_gcode(
            self.job(save=True).pk, b"; generated\nG1 X1 Y1 E0.5\n",
        )
        regular = FileAsset.objects.create(
            owner=self.user, category="source", name="my-code.py",
            metadata={"extension": ".py"},
        )
        self.assertIn(str(output.pk), self.library_ids())
        self.assertIn(str(regular.pk), self.library_ids())

    def test_existing_registered_profiles_hide_without_deletion(self):
        original = FileAsset.objects.create(
            owner=self.user, category="source", name="Legacy Creality K2.json",
            metadata={"extension": ".json"},
        )
        profile = SlicerProfile.objects.create(
            owner=self.user, engine="orcaslicer", engine_version="2.4.2",
            kind="printer", name="Legacy Creality K2",
            file_asset=original, content_sha256="a" * 64, status="candidate",
        )
        unlinked = FileAsset.objects.create(
            owner=self.user, category="source", name="my-script.py",
            metadata={"extension": ".py"},
        )
        ids = self.library_ids()
        self.assertNotIn(str(original.pk), ids)
        self.assertIn(str(unlinked.pk), ids)
        self.assertTrue(FileAsset.objects.filter(pk=original.pk).exists())
        self.assertTrue(SlicerProfile.objects.filter(pk=profile.pk).exists())
        response = self.client.get("/api/printing/slicer/profiles/")
        self.assertEqual(response.status_code, 200, response.content)
        self.assertIn(str(profile.pk), str(response.json()))

    def test_orphaned_internal_profile_and_legacy_unsaved_gcode_stay_hidden(self):
        internal = FileAsset.objects.create(
            owner=self.user, category="source", name="custom-process.json",
            metadata={"extension": ".json", "slicer_profile_internal": True},
        )
        legacy = FileAsset.objects.create(
            owner=self.user, category="other", name="older.gcode",
            metadata={"extension": ".gcode", "generated_by": "makervault-slicer"},
        )
        self.assertNotIn(str(internal.pk), self.library_ids())
        self.assertNotIn(str(legacy.pk), self.library_ids())
        self.assertNotIn(str(legacy.pk), self.printing_ids("gcode_files"))
