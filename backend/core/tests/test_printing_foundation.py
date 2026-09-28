import shutil
import tempfile
from datetime import timedelta
from decimal import Decimal
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.utils import timezone

from core.filament_catalogue import normalise_spoolmandb_row
from core.tasks import printing_integrations_tick

from core.models import (
    ExternalSpoolLink,
    FileAsset,
    FilamentManufacturer,
    FilamentProduct,
    Manufacturer,
    Model3D,
    ModelRevision,
    ModelRevisionAsset,
    Printer,
    PrinterCatalogModel,
    PrinterFilamentSlot,
    PrinterManufacturer,
    PrintingIntegrationSetting,
    PrintingLocation,
    PrintJob,
    PrintMaterialUsage,
    Spool,
)


class FilamentCatalogueTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_superuser(
            username="catalogue-admin",
            email="catalogue@example.com",
            password="test-password",
        )
        self.client.force_login(self.user)

    def sample_catalogue_item(self):
        return {
            "external_id": "example_pla_rainbow_1000_175_p",
            "manufacturer": "Example",
            "name": "Rainbow PLA",
            "material": "PLA",
            "density_g_cm3": 1.24,
            "diameter_mm": 1.75,
            "nominal_weight_g": 1000,
            "empty_spool_weight_g": 220,
            "spool_type": "plastic",
            "color_name": "",
            "color_hex": "#ff0000",
            "color_hexes": ["#ff0000", "#00ff0080", "#0000ff"],
            "transparency": "transparent",
            "multi_color_direction": "longitudinal",
            "finish": "glossy",
            "pattern": "",
            "glow": False,
            "nozzle_temp_min_c": 200,
            "nozzle_temp_max_c": 220,
            "bed_temp_min_c": 50,
            "bed_temp_max_c": 60,
            "source_name": "SpoolmanDB",
            "source_url": "https://donkie.github.io/SpoolmanDB/",
            "source_license": "MIT",
            "raw": {"id": "example_pla_rainbow_1000_175_p"},
        }

    def test_spoolmandb_normaliser_preserves_multicolour_and_alpha(self):
        item = normalise_spoolmandb_row({
            "id": "example_pla_rainbow_1000_175_p",
            "manufacturer": "Example",
            "name": "Rainbow PLA",
            "material": "PLA",
            "density": 1.24,
            "weight": 1000,
            "spool_weight": 220,
            "spool_type": "plastic",
            "diameter": 1.75,
            "color_hexes": ["FF0000", "00FF0080", "0000FF"],
            "multi_color_direction": "longitudinal",
            "extruder_temp_range": [200, 220],
            "bed_temp_range": [50, 60],
        })
        self.assertIsNotNone(item)
        self.assertEqual(item["color_hex"], "#ff0000")
        self.assertEqual(item["color_hexes"], ["#ff0000", "#00ff0080", "#0000ff"])
        self.assertEqual(item["transparency"], "transparent")
        self.assertEqual(item["multi_color_direction"], "longitudinal")
        self.assertEqual(item["nozzle_temp_min_c"], 200)
        self.assertEqual(item["nozzle_temp_max_c"], 220)

    @patch("core.api_views.search_spoolmandb")
    def test_catalogue_search_api_returns_source_and_rows(self, search_mock):
        sample = self.sample_catalogue_item()
        search_mock.return_value = {
            "rows": [sample],
            "total": 1,
            "offset": 0,
            "limit": 50,
            "source": {"name": "SpoolmanDB", "url": sample["source_url"], "license": "MIT"},
        }
        response = self.client.get("/api/printing/catalogue/filaments/?q=rainbow")
        self.assertEqual(response.status_code, 200, response.content)
        payload = response.json()
        self.assertEqual(payload["total"], 1)
        self.assertEqual(payload["rows"][0]["external_id"], sample["external_id"])
        self.assertEqual(payload["source"]["license"], "MIT")

    @patch("core.api_views.get_spoolmandb_item")
    def test_catalogue_import_creates_native_filament_with_provenance(self, item_mock):
        sample = self.sample_catalogue_item()
        item_mock.return_value = sample
        response = self.client.post(
            "/api/printing/catalogue/filaments/import/",
            data={"external_id": sample["external_id"]},
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 201, response.content)
        payload = response.json()
        self.assertTrue(payload["created"])
        filament = FilamentProduct.objects.get(pk=payload["item"]["id"])
        self.assertEqual(filament.filament_manufacturer.name, "Example")
        self.assertEqual(filament.source.source_type, "spoolmandb")
        self.assertEqual(filament.source.external_id, sample["external_id"])
        self.assertEqual(filament.color_hexes, sample["color_hexes"])
        self.assertEqual(filament.transparency, "transparent")
        self.assertEqual(filament.multi_color_direction, "longitudinal")
        self.assertEqual(filament.profile_data["source_license"], "MIT")

        second = self.client.post(
            "/api/printing/catalogue/filaments/import/",
            data={"external_id": sample["external_id"]},
            content_type="application/json",
        )
        self.assertEqual(second.status_code, 200, second.content)
        self.assertFalse(second.json()["created"])
        self.assertEqual(FilamentProduct.objects.filter(source__external_id=sample["external_id"]).count(), 1)


class PrintingFoundationTests(TestCase):
    def setUp(self):
        self.media_root = tempfile.mkdtemp(prefix="makervault-printing-")
        self.override = override_settings(MEDIA_ROOT=Path(self.media_root))
        self.override.enable()
        self.addCleanup(self.override.disable)
        self.addCleanup(shutil.rmtree, self.media_root, True)

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

    def test_filament_creation_supports_transparent_custom_colour(self):
        response = self.client.post(
            "/api/printing/filaments/",
            data={
                "manufacturer_id": str(self.manufacturer.id),
                "name": "Clear PETG",
                "material": "PETG",
                "color_name": "Crystal Clear",
                "color_hex": "#bfe8ff",
                "transparency": "transparent",
                "diameter_mm": "1.75",
                "nominal_weight_g": "1000",
            },
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 201, response.content)
        payload = response.json()["item"]
        self.assertEqual(payload["color_hex"], "#bfe8ff")
        self.assertEqual(payload["transparency"], "transparent")
        self.assertEqual(payload["transparency_label"], "Transparent")
        created = FilamentProduct.objects.get(pk=payload["id"])
        self.assertEqual(created.transparency, "transparent")

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
        print_job = PrintJob.objects.create(
            model_revision=revision,
            printer=self.printer,
            status="success",
            quantity=1,
        )
        PrintMaterialUsage.objects.create(
            print_job=print_job,
            spool=self.spool,
            filament=self.filament,
            printer_slot=slot,
            used_g="15.5",
            waste_g="0.5",
            material_cost="0.42",
            currency="GBP",
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
        self.assertEqual(payload["recent_prints"][0]["filament_used_g"], 15.5)
        self.assertEqual(payload["recent_prints"][0]["waste_g"], 0.5)
        self.assertEqual(payload["recent_prints"][0]["material_cost"], 0.42)
        self.assertEqual(payload["recent_prints"][0]["material_usages"][0]["spool"], "SPL-0001")

    def test_unmatched_discovered_slot_can_be_added_to_inventory_with_existing_filament(self):
        slot = PrinterFilamentSlot.objects.create(
            printer=self.printer,
            system="creality_cfs",
            unit_index=0,
            slot_index=0,
            material="PLA",
            color_hex="#7b1fa2",
            is_loaded=True,
            last_seen_at=timezone.now(),
            metadata={
                "vendor": "eSUN",
                "product_name": "PLA+ HS",
                "remaining_percent": 99,
                "rfid_detected": True,
            },
        )

        response = self.client.post(
            f"/api/printing/slots/{slot.id}/add-to-inventory/",
            data={
                "filament_id": str(self.filament.id),
                "initial_weight_g": "1000",
                "status": "open",
            },
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 201, response.content)
        payload = response.json()
        self.assertFalse(payload["created_filament"])
        self.assertEqual(payload["item"]["spool_id"], "SPL-0002")
        self.assertEqual(payload["item"]["assigned_printer_id"], str(self.printer.id))
        self.assertEqual(payload["item"]["remaining_weight_g"], 990.0)

        slot.refresh_from_db()
        self.assertIsNotNone(slot.spool_id)
        self.assertEqual(slot.spool.spool_id, "SPL-0002")
        self.assertEqual(slot.remaining_weight_g, Decimal("990.00"))

    def test_discovered_slot_framework_can_create_filament_for_future_provider(self):
        slot = PrinterFilamentSlot.objects.create(
            printer=self.printer,
            system="bambu_ams",
            unit_index=0,
            slot_index=2,
            material="PETG",
            color_hex="#8844cc",
            external_ref="ams:0:2",
            rfid_uid="RFID-FUTURE",
            is_loaded=True,
            last_seen_at=timezone.now(),
            metadata={
                "vendor": "Example Future Vendor",
                "product_name": "Rapid PETG",
                "remaining_percent": 75,
                "rfid_detected": True,
            },
        )

        response = self.client.post(
            f"/api/printing/slots/{slot.id}/add-to-inventory/",
            data={
                "new_filament": {
                    "manufacturer_name": "Example Future Vendor",
                    "name": "Rapid PETG",
                    "material": "PETG",
                    "color_name": "Purple",
                    "color_hex": "#8844cc",
                    "diameter_mm": "1.75",
                    "nominal_weight_g": "1000",
                },
                "initial_weight_g": "1000",
                "status": "open",
            },
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 201, response.content)
        payload = response.json()
        self.assertTrue(payload["created_filament"])
        self.assertEqual(payload["item"]["remaining_weight_g"], 750.0)

        slot.refresh_from_db()
        filament = slot.spool.filament
        self.assertEqual(filament.filament_manufacturer.name, "Example Future Vendor")
        self.assertEqual(filament.name, "Rapid PETG")
        self.assertEqual(filament.material, "PETG")
        self.assertEqual(filament.color_name, "Purple")
        self.assertEqual(filament.profile_data["discovered_from"]["system"], "bambu_ams")
        self.assertEqual(filament.profile_data["discovered_from"]["external_ref"], "ams:0:2")

    def test_print_job_supports_multiple_spools_and_aggregates_material_usage(self):
        second_filament = FilamentProduct.objects.create(
            manufacturer=self.manufacturer,
            name="PETG Accent",
            material="PETG",
            color_name="White",
            color_hex="#ffffff",
            diameter_mm="1.75",
        )
        second_spool = Spool.objects.create(
            spool_id="SPL-0002",
            filament=second_filament,
            initial_weight_g="1000",
            remaining_weight_g="800",
            status="open",
        )
        job = PrintJob.objects.create(
            printer=self.printer,
            status="success",
            quantity=1,
        )
        PrintMaterialUsage.objects.create(
            print_job=job,
            spool=self.spool,
            used_g="12.25",
            waste_g="0.25",
            material_cost="0.30",
            currency="GBP",
        )
        PrintMaterialUsage.objects.create(
            print_job=job,
            spool=second_spool,
            used_g="3.75",
            waste_g="0.10",
            material_cost="0.12",
            currency="GBP",
        )

        response = self.client.get("/api/printing/")
        self.assertEqual(response.status_code, 200)
        recent = response.json()["recent_prints"][0]
        self.assertEqual(len(recent["material_usages"]), 2)
        self.assertEqual(recent["filament_used_g"], 16.0)
        self.assertEqual(recent["waste_g"], 0.35)
        self.assertEqual(recent["material_cost"], 0.42)
        self.assertEqual(
            {usage["spool"] for usage in recent["material_usages"]},
            {"SPL-0001", "SPL-0002"},
        )

    def test_print_history_api_accepts_multiple_material_usages(self):
        second_filament = FilamentProduct.objects.create(
            manufacturer=self.manufacturer,
            name="PLA White",
            material="PLA",
            color_name="White",
            diameter_mm="1.75",
        )
        second_spool = Spool.objects.create(
            spool_id="SPL-HISTORY-2",
            filament=second_filament,
            initial_weight_g="1000",
            remaining_weight_g="900",
            status="open",
        )

        response = self.client.post(
            "/api/printing/jobs/",
            data={
                "printer_id": str(self.printer.id),
                "status": "success",
                "quantity": 1,
                "actual_minutes": 42,
                "material_usages": [
                    {"spool_id": str(self.spool.id), "used_g": "10.5", "waste_g": "0.2"},
                    {"spool_id": str(second_spool.id), "used_g": "2.5", "waste_g": "0.1"},
                ],
            },
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 201, response.content)
        job = response.json()["job"]
        self.assertEqual(len(job["material_usages"]), 2)
        self.assertEqual(job["filament_used_g"], 13.0)
        self.assertEqual(job["waste_g"], 0.3)
        self.assertEqual(PrintJob.objects.count(), 1)
        self.assertEqual(PrintMaterialUsage.objects.count(), 2)

    def test_print_history_rejects_slot_from_another_printer(self):
        other_printer = Printer.objects.create(name="Other printer", model="Other")
        foreign_slot = PrinterFilamentSlot.objects.create(
            printer=other_printer,
            system="creality_cfs",
            slot_index=0,
            spool=self.spool,
        )
        response = self.client.post(
            "/api/printing/jobs/",
            data={
                "printer_id": str(self.printer.id),
                "status": "success",
                "material_usages": [
                    {"printer_slot_id": str(foreign_slot.id), "used_g": "1"},
                ],
            },
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(PrintJob.objects.count(), 0)
        self.assertEqual(PrintMaterialUsage.objects.count(), 0)

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
        self.assertEqual(spool_response.json()["item"]["spool_id"], "SPL-0002")
        self.assertEqual(Spool.objects.filter(spool_id="SPL-0002").count(), 1)
        self.assertEqual(Model3D.objects.filter(name="Cable clip").count(), 1)

    def test_owned_printer_catalogue_populates_specs_location_and_connection(self):
        maker = PrinterManufacturer.objects.create(name="Creality")
        model = PrinterCatalogModel.objects.create(
            manufacturer=maker,
            name="K2",
            build_volume_x_mm="260",
            build_volume_y_mm="260",
            build_volume_z_mm="260",
            nozzle_mm="0.4",
            multi_material_system="creality_cfs",
            features={"cfs": True},
        )
        location = PrintingLocation.objects.create(name="Office", kind="room")

        response = self.client.post(
            "/api/printing/printers/",
            data={
                "printer_manufacturer_id": str(maker.id),
                "catalog_model_id": str(model.id),
                "name": "Office K2",
                "location_id": str(location.id),
                "connection_host": "192.168.1.34",
                "is_active": True,
            },
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 201, response.content)
        payload = response.json()["item"]
        self.assertEqual(payload["manufacturer"], "Creality")
        self.assertEqual(payload["model"], "K2")
        self.assertEqual(payload["build_volume"]["x"], 260.0)
        self.assertEqual(payload["build_volume"]["z"], 260.0)
        self.assertEqual(payload["location"], "Office")
        self.assertEqual(payload["connection_host"], "192.168.1.34")
        self.assertTrue(payload["is_active"])
        self.assertEqual(payload["catalogue"]["multi_material_system"], "creality_cfs")

    def test_spool_can_use_structured_location_or_printer(self):
        location = PrintingLocation.objects.create(name="Dry box 1", kind="drybox")
        stored = self.client.post(
            "/api/printing/spools/",
            data={
                "filament_id": str(self.filament.id),
                "storage_location_id": str(location.id),
                "remaining_weight_g": "800",
            },
            content_type="application/json",
        )
        self.assertEqual(stored.status_code, 201, stored.content)
        self.assertEqual(stored.json()["item"]["spool_id"], "SPL-0002")
        self.assertEqual(stored.json()["item"]["location"], "Dry box 1")
        self.assertEqual(stored.json()["item"]["placement_type"], "location")

        assigned = self.client.post(
            "/api/printing/spools/",
            data={
                "filament_id": str(self.filament.id),
                "assigned_printer_id": str(self.printer.id),
                "remaining_weight_g": "700",
            },
            content_type="application/json",
        )
        self.assertEqual(assigned.status_code, 201, assigned.content)
        self.assertEqual(assigned.json()["item"]["spool_id"], "SPL-0003")
        self.assertEqual(assigned.json()["item"]["location"], "Workshop printer")
        self.assertEqual(assigned.json()["item"]["placement_type"], "printer")

        invalid = self.client.post(
            "/api/printing/spools/",
            data={
                "filament_id": str(self.filament.id),
                "storage_location_id": str(location.id),
                "assigned_printer_id": str(self.printer.id),
            },
            content_type="application/json",
        )
        self.assertEqual(invalid.status_code, 400)

    def test_model_create_can_upload_local_stl_and_create_initial_revision(self):
        response = self.client.post(
            "/api/printing/models/",
            {
                "name": "Uploaded bracket",
                "revision_version": "1.0",
                "description": "Uploaded directly from Add Model",
                "file": SimpleUploadedFile(
                    "uploaded-bracket.stl",
                    b"solid bracket\nendsolid bracket\n",
                    content_type="model/stl",
                ),
            },
        )
        self.assertEqual(response.status_code, 201, response.content)
        model = Model3D.objects.get(name="Uploaded bracket")
        revision = ModelRevision.objects.get(model=model, version="1.0")
        link = ModelRevisionAsset.objects.get(revision=revision)
        self.assertEqual(link.role, "model")
        self.assertTrue(link.is_primary)
        self.assertEqual(link.file_asset.category, "mesh")
        self.assertEqual(link.file_asset.metadata["uploaded_from"], "printing_model")
        self.assertTrue(link.file_asset.file.storage.exists(link.file_asset.file.name))

    @patch("core.api_views.probe_spoolman")
    def test_printing_integration_settings_report_spoolman_and_cfs_status(self, probe_mock):
        probe_mock.return_value = {
            "endpoint_url": "http://spoolman.local:7912",
            "info": {"version": "test"},
        }
        maker = PrinterManufacturer.objects.create(name="Creality")
        model = PrinterCatalogModel.objects.create(
            manufacturer=maker,
            name="K2",
            multi_material_system="creality_cfs",
        )
        Printer.objects.create(
            name="CFS printer",
            printer_manufacturer=maker,
            catalog_model=model,
            model="K2",
            connection_host="192.168.1.34",
            is_active=True,
        )

        settings_response = self.client.get("/api/settings/printing-integrations/")
        self.assertEqual(settings_response.status_code, 200, settings_response.content)
        providers = {row["provider"] for row in settings_response.json()["rows"]}
        self.assertIn("spoolman", providers)
        self.assertIn("creality_cfs", providers)

        configure = self.client.patch(
            "/api/settings/printing-integrations/spoolman/",
            data={
                "enabled": True,
                "endpoint_url": "http://spoolman.local:7912",
                "sync_direction": "bidirectional",
            },
            content_type="application/json",
        )
        self.assertEqual(configure.status_code, 200, configure.content)

        tested = self.client.post("/api/settings/printing-integrations/spoolman/test/")
        self.assertEqual(tested.status_code, 200, tested.content)
        self.assertEqual(tested.json()["item"]["status"], "connected")

        cfs = self.client.patch(
            "/api/settings/printing-integrations/creality_cfs/",
            data={"enabled": True, "sync_direction": "import"},
            content_type="application/json",
        )
        self.assertEqual(cfs.status_code, 200, cfs.content)
        self.assertEqual(cfs.json()["item"]["status"], "disconnected")
        self.assertEqual(cfs.json()["item"]["compatible_printers"], 1)
        self.assertEqual(cfs.json()["item"]["configured_printers"], 1)

    @patch("core.printing_sync.requests.get")
    def test_spoolman_sync_imports_remote_spool_with_generated_local_id(self, get_mock):
        response = Mock(status_code=200)
        response.json.return_value = [
            {
                "id": 42,
                "remaining_weight": 612.5,
                "archived": False,
                "location": "Filament shelf",
                "comment": "Imported from Spoolman",
                "filament": {
                    "id": 7,
                    "name": "Hyper ABS",
                    "material": "ABS",
                    "color_hex": "FFFFFF",
                    "diameter": 1.75,
                    "density": 1.04,
                    "weight": 1000,
                    "spool_weight": 220,
                    "vendor": {"id": 3, "name": "Creality"},
                },
            }
        ]
        get_mock.return_value = response
        PrintingIntegrationSetting.objects.update_or_create(
            provider="spoolman",
            defaults={
                "enabled": True,
                "endpoint_url": "https://spoolman.example.test",
                "sync_direction": "import",
                "status": "disconnected",
            },
        )

        synced = self.client.post("/api/settings/printing-integrations/spoolman/sync/")
        self.assertEqual(synced.status_code, 200, synced.content)
        result = synced.json()["result"]
        self.assertEqual(result["created"], 1)
        self.assertEqual(result["remote_spools"], 1)

        imported = Spool.objects.get(spool_id="SPL-0002")
        self.assertEqual(imported.remaining_weight_g, Decimal("612.5"))
        self.assertEqual(imported.storage_location.name, "Filament shelf")
        self.assertEqual(imported.filament.material, "ABS")
        self.assertEqual(imported.filament.filament_manufacturer.name, "Creality")
        link = ExternalSpoolLink.objects.get(spool=imported, provider="spoolman")
        self.assertEqual(link.external_id, "42")
        setting = PrintingIntegrationSetting.objects.get(provider="spoolman")
        self.assertEqual(setting.status, "connected")
        self.assertIsNotNone(setting.last_sync_at)

    @patch("core.printing_sync.requests.get")
    def test_first_spoolman_sync_queues_possible_duplicate_for_review(self, get_mock):
        maker = FilamentManufacturer.objects.create(name="Creality")
        filament = FilamentProduct.objects.create(
            filament_manufacturer=maker,
            name="Hyper ABS",
            material="ABS",
            color_hex="#ffffff",
            diameter_mm="1.75",
        )
        local_location = PrintingLocation.objects.create(
            name="MakerVault shelf",
            kind="shelf",
        )
        local = Spool.objects.create(
            spool_id="SPL-LOCAL",
            filament=filament,
            initial_weight_g="1000",
            remaining_weight_g="900",
            storage_location=local_location,
            status="drying",
            notes="Local notes stay authoritative",
        )
        response = Mock(status_code=200)
        response.json.return_value = [
            {
                "id": 99,
                "remaining_weight": 450,
                "initial_weight": 1000,
                "archived": True,
                "location": "Spoolman shelf",
                "comment": "Remote note must not replace local notes",
                "filament": {
                    "id": 8,
                    "name": "Hyper ABS",
                    "material": "ABS",
                    "color_hex": "FFFFFF",
                    "diameter": 1.75,
                    "density": 1.04,
                    "weight": 1000,
                    "vendor": {"id": 3, "name": "Creality"},
                },
            }
        ]
        get_mock.return_value = response
        PrintingIntegrationSetting.objects.update_or_create(
            provider="spoolman",
            defaults={
                "enabled": True,
                "endpoint_url": "https://spoolman.example.test",
                "sync_direction": "import",
                "status": "disconnected",
            },
        )

        synced = self.client.post("/api/settings/printing-integrations/spoolman/sync/")
        self.assertEqual(synced.status_code, 200, synced.content)
        result = synced.json()["result"]
        self.assertEqual(result["created"], 0)
        self.assertEqual(result["pending_review"], 1)
        self.assertEqual(Spool.objects.filter(filament=filament).count(), 1)
        self.assertFalse(ExternalSpoolLink.objects.filter(provider="spoolman", external_id="99").exists())
        self.assertTrue(PrintingLocation.objects.filter(name="Spoolman shelf").exists())

        local.refresh_from_db()
        self.assertEqual(local.remaining_weight_g, Decimal("900"))
        self.assertEqual(local.storage_location, local_location)
        self.assertEqual(local.status, "drying")
        self.assertEqual(local.notes, "Local notes stay authoritative")

        reviews = self.client.get("/api/settings/printing-integrations/spoolman/reviews/")
        self.assertEqual(reviews.status_code, 200, reviews.content)
        self.assertEqual(len(reviews.json()["rows"]), 1)
        self.assertEqual(reviews.json()["rows"][0]["external_id"], "99")
        self.assertEqual(reviews.json()["rows"][0]["spool_candidates"][0]["id"], str(local.id))

        resolved = self.client.post(
            "/api/settings/printing-integrations/spoolman/reviews/99/",
            data={"action": "link", "spool_id": str(local.id)},
            content_type="application/json",
        )
        self.assertEqual(resolved.status_code, 200, resolved.content)
        self.assertEqual(resolved.json()["item"]["pending_review_count"], 0)
        self.assertEqual(
            ExternalSpoolLink.objects.get(provider="spoolman", external_id="99").spool_id,
            local.id,
        )

        local.refresh_from_db()
        self.assertEqual(local.remaining_weight_g, Decimal("450"))
        self.assertEqual(local.storage_location, local_location)
        self.assertEqual(local.status, "drying")
        self.assertEqual(local.notes, "Local notes stay authoritative")

    @patch("core.printing_sync._fetch_cfs_boxs_info", new_callable=AsyncMock)
    def test_creality_cfs_sync_populates_slots_and_matches_assigned_spool(self, fetch_mock):
        maker = PrinterManufacturer.objects.create(name="Creality")
        model = PrinterCatalogModel.objects.create(
            manufacturer=maker,
            name="K2",
            multi_material_system="creality_cfs",
        )
        printer = Printer.objects.create(
            name="Dining room K2",
            printer_manufacturer=maker,
            catalog_model=model,
            model="K2",
            connection_host="192.168.1.34",
            is_active=True,
        )
        filament_maker = FilamentManufacturer.objects.create(name="Creality")
        filament = FilamentProduct.objects.create(
            filament_manufacturer=filament_maker,
            name="White Hyper ABS",
            material="ABS",
            color_name="White",
            color_hex="#ffffff",
            nominal_weight_g="1000",
            diameter_mm="1.75",
        )
        spool = Spool.objects.create(
            spool_id="SPL-CFS-LOCAL",
            rfid_uid="12345",
            filament=filament,
            assigned_printer=printer,
            initial_weight_g="1000",
            remaining_weight_g="900",
            status="open",
        )
        fetch_mock.return_value = {
            "materialBoxs": [
                {
                    "id": 1,
                    "state": 1,
                    "type": 0,
                    "temp": 27.0,
                    "humidity": 42.0,
                    "materials": [
                        {
                            "id": 0,
                            "vendor": "Creality",
                            "type": "ABS",
                            "name": "Hyper ABS",
                            "rfid": "12345",
                            "color": "#0ffffff",
                            "percent": 30,
                            "state": 2,
                            "selected": 1,
                            "minTemp": 240,
                            "maxTemp": 280,
                        }
                    ],
                }
            ]
        }
        PrintingIntegrationSetting.objects.update_or_create(
            provider="creality_cfs",
            defaults={
                "enabled": True,
                "sync_direction": "import",
                "status": "disconnected",
            },
        )

        synced = self.client.post("/api/settings/printing-integrations/creality_cfs/sync/")
        self.assertEqual(synced.status_code, 200, synced.content)
        result = synced.json()["result"]
        self.assertEqual(result["loaded_slots"], 1)
        self.assertEqual(result["matched_spools"], 1)

        slot = PrinterFilamentSlot.objects.get(
            printer=printer,
            system="creality_cfs",
            unit_index=0,
            slot_index=0,
        )
        self.assertEqual(slot.spool_id, spool.id)
        self.assertEqual(slot.rfid_uid, "12345")
        self.assertEqual(slot.spool.rfid_uid, "12345")
        self.assertEqual(slot.material, "ABS")
        self.assertEqual(slot.color_hex, "#ffffff")
        self.assertEqual(slot.metadata["vendor"], "Creality")
        self.assertTrue(slot.metadata["rfid_detected"])
        self.assertEqual(slot.metadata["remaining_percent"], 30.0)
        spool.refresh_from_db()
        self.assertEqual(spool.remaining_weight_g, Decimal("300.00"))
        setting = PrintingIntegrationSetting.objects.get(provider="creality_cfs")
        self.assertEqual(setting.status, "connected")
        self.assertIsNotNone(setting.last_sync_at)

    @patch("core.printing_sync._fetch_cfs_boxs_info", new_callable=AsyncMock)
    def test_cfs_does_not_merge_same_filament_or_different_colour_without_matching_rfid(self, fetch_mock):
        maker = PrinterManufacturer.objects.create(name="Creality RFID Test")
        model = PrinterCatalogModel.objects.create(
            manufacturer=maker,
            name="K2 RFID Test",
            multi_material_system="creality_cfs",
        )
        printer = Printer.objects.create(
            name="RFID K2",
            printer_manufacturer=maker,
            catalog_model=model,
            model="K2 RFID Test",
            connection_host="192.0.2.10",
            is_active=True,
        )
        filament_maker = FilamentManufacturer.objects.create(name="Creality RFID Test")
        white = FilamentProduct.objects.create(
            filament_manufacturer=filament_maker,
            name="Hyper ABS",
            material="ABS",
            color_name="White",
            color_hex="#ffffff",
            nominal_weight_g="1000",
            diameter_mm="1.75",
        )
        black = FilamentProduct.objects.create(
            filament_manufacturer=filament_maker,
            name="Hyper ABS",
            material="ABS",
            color_name="Black",
            color_hex="#000000",
            nominal_weight_g="1000",
            diameter_mm="1.75",
        )
        white_spool = Spool.objects.create(
            spool_id="SPL-RFID-WHITE",
            rfid_uid="RFID-WHITE",
            filament=white,
            assigned_printer=printer,
            initial_weight_g="1000",
            remaining_weight_g="800",
            status="open",
        )
        first_black = Spool.objects.create(
            spool_id="SPL-RFID-BLACK-1",
            rfid_uid="RFID-BLACK-1",
            filament=black,
            initial_weight_g="1000",
            remaining_weight_g="950",
            status="open",
        )

        fetch_mock.return_value = {
            "materialBoxs": [{
                "id": 1,
                "state": 1,
                "type": 0,
                "materials": [
                    {
                        "id": 0, "vendor": "Creality RFID Test", "type": "ABS",
                        "name": "Hyper ABS", "rfid": "RFID-WHITE",
                        "color": "#0ffffff", "percent": 70, "state": 2,
                    },
                    {
                        "id": 1, "vendor": "Creality RFID Test", "type": "ABS",
                        "name": "Hyper ABS", "rfid": "RFID-BLACK-2",
                        "color": "#000000", "percent": 90, "state": 2,
                    },
                ],
            }],
        }
        PrintingIntegrationSetting.objects.update_or_create(
            provider="creality_cfs",
            defaults={
                "enabled": True,
                "sync_direction": "import",
                "status": "disconnected",
            },
        )

        synced = self.client.post("/api/settings/printing-integrations/creality_cfs/sync/")
        self.assertEqual(synced.status_code, 200, synced.content)
        self.assertEqual(synced.json()["result"]["matched_spools"], 1)

        white_slot = PrinterFilamentSlot.objects.get(
            printer=printer, system="creality_cfs", unit_index=0, slot_index=0
        )
        black_slot = PrinterFilamentSlot.objects.get(
            printer=printer, system="creality_cfs", unit_index=0, slot_index=1
        )
        self.assertEqual(white_slot.spool_id, white_spool.id)
        self.assertEqual(white_slot.rfid_uid, "RFID-WHITE")
        self.assertIsNone(black_slot.spool_id)
        self.assertEqual(black_slot.rfid_uid, "RFID-BLACK-2")
        first_black.refresh_from_db()
        self.assertEqual(first_black.remaining_weight_g, Decimal("950"))

        added = self.client.post(
            f"/api/printing/slots/{black_slot.id}/add-to-inventory/",
            data={
                "filament_id": str(black.id),
                "initial_weight_g": "1000",
                "status": "open",
            },
            content_type="application/json",
        )
        self.assertEqual(added.status_code, 201, added.content)
        created = Spool.objects.get(pk=added.json()["item"]["id"])
        self.assertEqual(created.rfid_uid, "RFID-BLACK-2")
        self.assertEqual(created.filament_id, black.id)
        self.assertNotEqual(created.id, first_black.id)
        self.assertEqual(
            Spool.objects.filter(filament=black).count(),
            2,
        )

    def test_physical_spool_rfid_is_unique_and_serialised(self):
        response = self.client.post(
            "/api/printing/spools/",
            data={
                "filament_id": str(self.filament.id),
                "rfid_uid": " abc-123 ",
                "status": "open",
            },
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 201, response.content)
        self.assertEqual(response.json()["item"]["rfid_uid"], "ABC-123")

        duplicate = self.client.post(
            "/api/printing/spools/",
            data={
                "filament_id": str(self.filament.id),
                "rfid_uid": "abc-123",
                "status": "open",
            },
            content_type="application/json",
        )
        self.assertEqual(duplicate.status_code, 409, duplicate.content)

    def test_printing_overview_only_lists_enabled_integrations(self):
        PrintingIntegrationSetting.objects.update_or_create(
            provider="spoolman",
            defaults={"enabled": True, "status": "connected"},
        )
        PrintingIntegrationSetting.objects.update_or_create(
            provider="creality_cfs",
            defaults={"enabled": False, "status": "disabled"},
        )
        response = self.client.get("/api/printing/")
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(
            [item["provider"] for item in response.json()["integrations"]],
            ["spoolman"],
        )

    @patch("core.tasks.printing_integration_sync_task.delay")
    def test_enabled_scheduled_integration_is_queued_when_due(self, delay_mock):
        setting, _ = PrintingIntegrationSetting.objects.update_or_create(
            provider="spoolman",
            defaults={
                "enabled": True,
                "endpoint_url": "https://spoolman.example.test",
                "sync_direction": "import",
                "auto_sync": True,
                "sync_interval_minutes": 30,
                "next_sync_at": timezone.now() - timedelta(minutes=1),
            },
        )
        result = printing_integrations_tick()
        self.assertEqual(result["queued"], ["spoolman"])
        delay_mock.assert_called_once_with("spoolman", triggered_by="schedule")
        setting.refresh_from_db()
        self.assertGreater(setting.next_sync_at, timezone.now())

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
