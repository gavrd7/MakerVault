from decimal import Decimal
from unittest.mock import Mock, patch

from django.contrib.auth import get_user_model
from django.test import TestCase

from core.models import (
    ExternalPrinterLink,
    ExternalSpoolLink,
    FilamentManufacturer,
    FilamentProduct,
    Printer,
    PrinterFilamentSlot,
    PrintingIntegrationSetting,
    PrintJob,
    Spool,
)


class SimplyPrintIntegrationTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_superuser(
            username="simplyprint-admin",
            email="simplyprint@example.com",
            password="test-password",
        )
        self.client.force_login(self.user)

    def configure(self):
        response = self.client.patch(
            "/api/settings/printing-integrations/simplyprint/",
            data={
                "enabled": True,
                "endpoint_url": "https://api.simplyprint.io",
                "sync_direction": "import",
                "company_id": "123",
                "api_key": "sp-secret-key",
                "history_page_size": 50,
                "auto_sync": False,
            },
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200, response.content)
        return response.json()["item"]

    def test_settings_store_api_key_server_side_without_returning_it(self):
        item = self.configure()
        self.assertEqual(item["status"], "disconnected")
        self.assertEqual(item["config"]["company_id"], "123")
        self.assertTrue(item["config"]["api_key_configured"])
        self.assertNotIn("api_key", item["config"])

        setting = PrintingIntegrationSetting.objects.get(provider="simplyprint")
        self.assertEqual(setting.config["api_key"], "sp-secret-key")

        fetched = self.client.get("/api/settings/printing-integrations/")
        self.assertEqual(fetched.status_code, 200, fetched.content)
        row = next(row for row in fetched.json()["rows"] if row["provider"] == "simplyprint")
        self.assertTrue(row["config"]["api_key_configured"])
        self.assertNotIn("api_key", row["config"])

    @patch("core.printing_integrations.requests.get")
    def test_connection_probe_uses_company_id_and_api_key(self, get_mock):
        self.configure()
        response = Mock(status_code=200)
        response.json.return_value = {
            "status": True,
            "message": "Your API key is valid!",
        }
        get_mock.return_value = response

        tested = self.client.post("/api/settings/printing-integrations/simplyprint/test/")
        self.assertEqual(tested.status_code, 200, tested.content)
        self.assertEqual(tested.json()["item"]["status"], "connected")

        args, kwargs = get_mock.call_args
        self.assertEqual(args[0], "https://api.simplyprint.io/123/account/Test")
        self.assertEqual(kwargs["headers"]["X-API-KEY"], "sp-secret-key")

    def simplyprint_api_response(self, method, url, **kwargs):
        response = Mock(status_code=200)
        if url.endswith("/printers/Get"):
            response.json.return_value = {
                "status": True,
                "message": None,
                "page_amount": 1,
                "total": 1,
                "data": [
                    {
                        "id": 385,
                        "printer": {
                            "name": "Workshop K2",
                            "state": "printing",
                            "online": True,
                            "group": 99,
                            "groupName": "Workshop",
                            "api": "Moonraker",
                            "ui": "fluidd",
                            "ip": "192.0.2.50",
                            "firmware": "Klipper",
                            "firmwareVersion": "v0.12",
                            "spVersion": "1.3.13",
                            "temps": {"bed": 60, "tool0": 220},
                        },
                        "filament": {
                            "0": {
                                "id": 14817,
                                "extruder": 0,
                            }
                        },
                        "notifications": [],
                    }
                ],
            }
        elif url.endswith("/filament/GetFilament"):
            response.json.return_value = {
                "status": True,
                "message": None,
                "filament": {
                    "14817": {
                        "id": 14817,
                        "uid": "NBCU",
                        "type": {"id": 281, "name": "PLA"},
                        "brand": "eSUN",
                        "colorName": "Purple",
                        "colorHex": "#800080",
                        "dia": 1.75,
                        "nfcId": "04ABCDEF",
                        "qrId": "QR-14817",
                        "total": 335284,
                        "left": 234699,
                        "printer": 385,
                        "extruder": 0,
                    }
                },
            }
        elif url.endswith("/jobs/GetPaginatedPrintJobs"):
            response.json.return_value = {
                "status": True,
                "message": None,
                "page_amount": 1,
                "data": [
                    {
                        "id": 549145,
                        "uid": "7df103aa-b12c-4b33-8305-b55f91c11a4d",
                        "status": "finished",
                        "filename": "Benchy.gcode",
                        "startDate": "2026-09-20T10:00:00+00:00",
                        "endDate": "2026-09-20T11:30:00+00:00",
                        "printer": 385,
                        "filUsageGram": 12.345,
                        "outsideSystem": False,
                        "autoprint": False,
                    }
                ],
            }
        else:
            raise AssertionError(f"Unexpected SimplyPrint URL: {url}")
        return response

    @patch("core.printing_sync.requests.request")
    def test_sync_links_existing_printer_without_cloning_remote_filament_inventory(self, request_mock):
        self.configure()
        local = Printer.objects.create(owner=self.user, 
            name="Workshop K2",
            model="K2",
            serial_number="LOCAL-SERIAL",
            notes="MakerVault-owned note",
        )
        request_mock.side_effect = self.simplyprint_api_response

        synced = self.client.post("/api/settings/printing-integrations/simplyprint/sync/")
        self.assertEqual(synced.status_code, 200, synced.content)
        result = synced.json()["result"]
        self.assertEqual(result["remote_printers"], 1)
        self.assertEqual(result["printers_created"], 0)
        self.assertEqual(result["printers_linked_existing"], 1)
        self.assertEqual(result["remote_filaments"], 1)
        self.assertEqual(result["loaded_slots"], 1)
        self.assertEqual(result["jobs_created"], 1)

        self.assertEqual(Printer.objects.count(), 1)
        local.refresh_from_db()
        self.assertEqual(local.model, "K2")
        self.assertEqual(local.serial_number, "LOCAL-SERIAL")
        self.assertEqual(local.notes, "MakerVault-owned note")
        self.assertEqual(local.profile_data["simplyprint"]["state"], "printing")
        self.assertTrue(local.profile_data["simplyprint"]["online"])

        link = ExternalPrinterLink.objects.get(provider="simplyprint", external_id="385")
        self.assertEqual(link.printer_id, local.id)

        slot = PrinterFilamentSlot.objects.get(
            printer=local,
            system="simplyprint",
            unit_index=0,
            slot_index=0,
        )
        self.assertTrue(slot.is_loaded)
        self.assertIsNone(slot.spool_id)
        self.assertEqual(slot.material, "PLA")
        self.assertEqual(slot.color_name, "Purple")
        self.assertEqual(slot.color_hex, "#800080")
        self.assertEqual(slot.rfid_uid, "04ABCDEF")
        self.assertEqual(slot.metadata["external_spool_id"], "14817")
        self.assertEqual(Spool.objects.count(), 0)

        job = PrintJob.objects.get(settings__external_provider="simplyprint")
        self.assertEqual(job.printer_id, local.id)
        self.assertEqual(job.status, "success")
        self.assertEqual(job.actual_minutes, 90)
        usage = job.material_usages.get()
        self.assertEqual(usage.used_g, Decimal("12.35"))
        self.assertIsNone(usage.spool_id)
        self.assertIsNone(usage.filament_id)

        second = self.client.post("/api/settings/printing-integrations/simplyprint/sync/")
        self.assertEqual(second.status_code, 200, second.content)
        self.assertEqual(Printer.objects.count(), 1)
        self.assertEqual(PrintJob.objects.filter(settings__external_provider="simplyprint").count(), 1)

    @patch("core.printing_sync.requests.request")
    def test_explicit_slot_link_creates_exact_simplyprint_spool_mapping(self, request_mock):
        self.configure()
        printer = Printer.objects.create(owner=self.user, name="Workshop K2", model="K2")
        request_mock.side_effect = self.simplyprint_api_response
        synced = self.client.post("/api/settings/printing-integrations/simplyprint/sync/")
        self.assertEqual(synced.status_code, 200, synced.content)

        maker = FilamentManufacturer.objects.create(name="eSUN")
        filament = FilamentProduct.objects.create(
            filament_manufacturer=maker,
            name="PLA Basic",
            material="PLA",
            color_name="Purple",
            color_hex="#800080",
            diameter_mm="1.75",
        )
        spool = Spool.objects.create(owner=self.user, 
            spool_id="SPL-SP-0001",
            filament=filament,
            initial_weight_g="1000",
            remaining_weight_g="800",
            status="open",
        )
        slot = PrinterFilamentSlot.objects.get(printer=printer, system="simplyprint")

        linked = self.client.post(
            f"/api/printing/slots/{slot.id}/add-to-inventory/",
            data={"existing_spool_id": str(spool.id)},
            content_type="application/json",
        )
        self.assertEqual(linked.status_code, 200, linked.content)

        external = ExternalSpoolLink.objects.get(provider="simplyprint", external_id="14817")
        self.assertEqual(external.spool_id, spool.id)

        slot.spool = None
        slot.save(update_fields=["spool", "updated_at"])
        resynced = self.client.post("/api/settings/printing-integrations/simplyprint/sync/")
        self.assertEqual(resynced.status_code, 200, resynced.content)

        slot.refresh_from_db()
        self.assertEqual(slot.spool_id, spool.id)
        self.assertEqual(resynced.json()["result"]["exact_spool_links"], 1)
