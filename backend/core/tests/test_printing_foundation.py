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
