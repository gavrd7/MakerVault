from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import TestCase
from django.utils import timezone

from core.models import (
    ExternalSpoolLink,
    FileAsset,
    FilamentProduct,
    Manufacturer,
    Model3D,
    ModelRevision,
    ModelRevisionAsset,
    Printer,
    PrinterFilamentSlot,
    PrintJob,
    Spool,
)


class PrintingFoundationTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_superuser(
            username="printing-admin",
            email="printing@example.com",
            password="test-password",
        )
        self.client.force_login(self.user)
        self.manufacturer = Manufacturer.objects.create(name="Example Filament")
        self.filament = FilamentProduct.objects.create(
            manufacturer=self.manufacturer,
            name="PLA Basic",
            material="PLA",
            color_name="Blue",
            color_hex="#3366ff",
            diameter_mm="1.75",
        )
        self.spool = Spool.objects.create(
            spool_id="SPL-0001",
            filament=self.filament,
            initial_weight_g="1000",
            remaining_weight_g="725",
            status="open",
        )
        self.printer = Printer.objects.create(
            name="Workshop printer",
            model="K2",
            nozzle_mm="0.4",
        )

    def test_printing_overview_exposes_native_models_spools_and_slots(self):
        ExternalSpoolLink.objects.create(
            spool=self.spool,
            provider="spoolman",
            external_id="42",
            sync_direction="bidirectional",
        )
        slot = PrinterFilamentSlot.objects.create(
            printer=self.printer,
            system="creality_cfs",
            unit_index=0,
            slot_index=1,
            spool=self.spool,
            rfid_uid="RFID-ABC",
            material="PLA",
            color_name="Blue",
            color_hex="#3366ff",
            remaining_weight_g="710",
            is_loaded=True,
            last_seen_at=timezone.now(),
        )
        model = Model3D.objects.create(name="Desk enclosure", tags=["case"])
        revision = ModelRevision.objects.create(model=model, version="1.0")
        asset = FileAsset.objects.create(
            name="Desk enclosure STL",
            category="mesh",
            file="files/desk-enclosure.stl",
        )
        link = ModelRevisionAsset.objects.create(
            revision=revision,
            file_asset=asset,
            role="model",
            is_primary=True,
        )
        PrintJob.objects.create(
            model_revision=revision,
            printer=self.printer,
            spool=self.spool,
            status="success",
            filament_used_g="15.5",
            quantity=1,
        )

        response = self.client.get("/api/printing/")
        self.assertEqual(response.status_code, 200)
        payload = response.json()

        self.assertEqual(payload["summary"]["printers"], 1)
        self.assertEqual(payload["summary"]["models"], 1)
        self.assertEqual(payload["summary"]["spools"], 1)
        self.assertEqual(payload["summary"]["loaded_slots"], 1)
        self.assertEqual(payload["summary"]["externally_linked_spools"], 1)
        self.assertEqual(payload["summary"]["print_jobs"], 1)

        self.assertEqual(payload["printers"][0]["slots"][0]["id"], str(slot.id))
        self.assertEqual(payload["printers"][0]["slots"][0]["spool_code"], "SPL-0001")
        self.assertEqual(payload["spools"][0]["external_links"][0]["provider"], "spoolman")
        self.assertEqual(payload["models"][0]["revisions"][0]["assets"][0]["id"], str(link.id))
        self.assertEqual(payload["models"][0]["revisions"][0]["assets"][0]["file"]["category"], "mesh")
        self.assertEqual(payload["recent_prints"][0]["status"], "success")

    def test_model_revision_asset_reuses_fileasset_and_validates_printable_role(self):
        model = Model3D.objects.create(name="Calibration part")
        revision = ModelRevision.objects.create(model=model, version="A")
        document = FileAsset.objects.create(
            name="Instructions",
            category="document",
            file="files/instructions.pdf",
        )
        link = ModelRevisionAsset(
            revision=revision,
            file_asset=document,
            role="model",
        )
        with self.assertRaises(ValidationError):
            link.full_clean()

        reference = ModelRevisionAsset(
            revision=revision,
            file_asset=document,
            role="reference",
        )
        reference.full_clean()
        reference.save()
        self.assertEqual(reference.file_asset_id, document.id)

    def test_native_printing_crud_endpoints_create_core_records(self):
        filament_response = self.client.post(
            "/api/printing/filaments/",
            data={
                "manufacturer_id": self.manufacturer.id,
                "name": "PETG Tough",
                "material": "PETG",
                "color_name": "Black",
                "color_hex": "#111111",
                "diameter_mm": "1.75",
                "nominal_weight_g": "1000",
            },
            content_type="application/json",
        )
        self.assertEqual(filament_response.status_code, 201, filament_response.content)
        filament_id = filament_response.json()["item"]["id"]

        printer_response = self.client.post(
            "/api/printing/printers/",
            data={
                "name": "Desk printer",
                "model": "K1",
                "location": "Workshop",
                "build_volume_x_mm": "220",
                "build_volume_y_mm": "220",
                "build_volume_z_mm": "250",
                "nozzle_mm": "0.4",
            },
            content_type="application/json",
        )
        self.assertEqual(printer_response.status_code, 201, printer_response.content)

        spool_response = self.client.post(
            "/api/printing/spools/",
            data={
                "spool_id": "SPL-API-1",
                "filament_id": filament_id,
                "initial_weight_g": "1000",
                "remaining_weight_g": "950",
                "status": "open",
                "location": "Dry box",
            },
            content_type="application/json",
        )
        self.assertEqual(spool_response.status_code, 201, spool_response.content)

        model_response = self.client.post(
            "/api/printing/models/",
            data={
                "name": "Cable clip",
                "description": "Small printable cable clip",
                "tags": ["utility", "cable"],
            },
            content_type="application/json",
        )
        self.assertEqual(model_response.status_code, 201, model_response.content)

        self.assertEqual(Printer.objects.filter(name="Desk printer").count(), 1)
        self.assertEqual(Spool.objects.filter(spool_id="SPL-API-1").count(), 1)
        self.assertEqual(Model3D.objects.filter(name="Cable clip").count(), 1)

    def test_regular_user_cannot_create_native_printing_records(self):
        regular = get_user_model().objects.create_user(
            username="printing-viewer",
            password="test-password",
        )
        self.client.force_login(regular)
        response = self.client.post(
            "/api/printing/printers/",
            data={"name": "Blocked printer", "model": "Example"},
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 403)
        self.assertFalse(Printer.objects.filter(name="Blocked printer").exists())

    def test_model_revision_can_attach_existing_fileasset_without_duplication(self):
        model = Model3D.objects.create(name="Bracket")
        asset = FileAsset.objects.create(
            name="Bracket STL",
            category="mesh",
            file="files/bracket.stl",
        )

        revision_response = self.client.post(
            f"/api/printing/models/{model.id}/revisions/",
            data={"version": "1.0", "notes": "Initial revision"},
            content_type="application/json",
        )
        self.assertEqual(revision_response.status_code, 201, revision_response.content)
        revision_id = revision_response.json()["model"]["revisions"][0]["id"]

        attach_response = self.client.post(
            f"/api/printing/models/{model.id}/revisions/{revision_id}/assets/",
            data={"file_asset_id": str(asset.id), "role": "model", "is_primary": True},
            content_type="application/json",
        )
        self.assertEqual(attach_response.status_code, 201, attach_response.content)
        payload = attach_response.json()["model"]
        attached = payload["revisions"][0]["assets"][0]
        self.assertEqual(attached["file"]["id"], str(asset.id))
        self.assertTrue(attached["is_primary"])
        self.assertEqual(FileAsset.objects.filter(pk=asset.id).count(), 1)

    def test_model_linked_file_cannot_be_deleted_until_detached(self):
        model = Model3D.objects.create(name="Protected model")
        revision = ModelRevision.objects.create(model=model, version="1")
        asset = FileAsset.objects.create(
            name="Protected STL",
            category="mesh",
            file="files/protected.stl",
        )
        link = ModelRevisionAsset.objects.create(
            revision=revision,
            file_asset=asset,
            role="model",
        )

        response = self.client.delete(f"/api/files/{asset.id}/")
        self.assertEqual(response.status_code, 409)
        self.assertTrue(FileAsset.objects.filter(pk=asset.id).exists())

        detach = self.client.delete(
            f"/api/printing/models/{model.id}/revisions/{revision.id}/assets/{link.id}/"
        )
        self.assertEqual(detach.status_code, 200)

        response = self.client.delete(f"/api/files/{asset.id}/")
        self.assertEqual(response.status_code, 200)
        self.assertFalse(FileAsset.objects.filter(pk=asset.id).exists())

    def test_cross_project_model_file_attachment_is_rejected(self):
        from core.models import Project

        model_project = Project.objects.create(name="Model project")
        other_project = Project.objects.create(name="Other project")
        model = Model3D.objects.create(name="Project model", project=model_project)
        revision = ModelRevision.objects.create(model=model, version="1")
        asset = FileAsset.objects.create(
            name="Other STL",
            category="mesh",
            file="files/other.stl",
            project=other_project,
        )

        response = self.client.post(
            f"/api/printing/models/{model.id}/revisions/{revision.id}/assets/",
            data={"file_asset_id": str(asset.id), "role": "model"},
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 400)
        self.assertFalse(ModelRevisionAsset.objects.filter(revision=revision).exists())

    def test_external_provider_links_do_not_replace_native_spool_identity(self):
        link = ExternalSpoolLink.objects.create(
            spool=self.spool,
            provider="simplyprint",
            external_id="remote-123",
            sync_direction="import",
        )
        self.assertEqual(link.spool.spool_id, "SPL-0001")
        self.assertEqual(link.provider, "simplyprint")
        self.assertEqual(self.spool.external_links.count(), 1)
