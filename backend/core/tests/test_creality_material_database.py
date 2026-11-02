"""Safety and API regression tests for the read-only Creality catalogue mirror."""
import json
from unittest.mock import patch
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.test import TestCase

from core.creality_material_database import MaterialDatabaseError
from core.models import Printer, PrinterConnection


class CrealityMaterialDatabaseTests(TestCase):
    def setUp(self):
        self.owner = get_user_model().objects.create_user(username="printer-material-owner", password="test")
        self.other = get_user_model().objects.create_user(username="printer-material-other")
        self.owner.user_permissions.add(Permission.objects.get(
            content_type__app_label="core", codename="change_printer"
        ))
        self.printer = Printer.objects.create(owner=self.owner, name="Local CFS", model="K2")
        self.connection = PrinterConnection.objects.create(
            printer=self.printer, adapter="creality_local",
            enabled=True, endpoint_url="ws://192.0.2.44:9999",
        )
        self.client.force_login(self.owner)
        self.url = (
            f"/api/printing/printers/{self.printer.pk}/connections/"
            f"{self.connection.pk}/material-database/"
        )

    def test_read_only_pull_is_explicit_and_never_writes_printer_inventory(self):
        with patch("core.api_views.pull_creality_material_database") as pull:
            pull.return_value = {"top_level_items": 2, "bytes": 100, "synced_at": "2026-11-02T00:00:00Z"}
            self.assertEqual(self.client.get(self.url).status_code, 200)
            pull.assert_not_called()
            self.assertEqual(self.client.post(
                self.url, data=json.dumps({"action": "pull"}),
                content_type="application/json",
            ).status_code, 200)
            pull.assert_called_once()

    def test_configure_requires_permission_and_does_not_leak_credential(self):
        result = self.client.post(self.url, data=json.dumps({
            "action": "configure", "username": "root", "password": "top-secret",
            "fingerprint": "SHA256:example", "scheduled": True,
        }), content_type="application/json")
        self.assertEqual(result.status_code, 200)
        self.assertNotIn("top-secret", result.content.decode())
        self.connection.refresh_from_db()
        self.assertTrue(self.connection.config["material_database_scheduled"])
        self.assertEqual(self.connection.config["material_ssh_password"], "top-secret")
        response = self.client.get(
            f"/api/printing/printers/{self.printer.pk}/connections/"
        )
        self.assertNotIn("top-secret", response.content.decode())
        self.owner.user_permissions.clear()
        self.assertEqual(self.client.post(
            self.url, data=json.dumps({"action": "pull"}),
            content_type="application/json",
        ).status_code, 403)

    def test_owner_isolation(self):
        self.client.force_login(self.other)
        self.assertEqual(self.client.get(self.url).status_code, 404)

    def test_failure_does_not_erase_cached_copy(self):
        config = {"material_database_snapshot": {"stored": ["PLA"]}}
        self.connection.config = config
        self.connection.save(update_fields=["config"])
        with patch("core.api_views.pull_creality_material_database", side_effect=MaterialDatabaseError("offline")):
            response = self.client.post(
                self.url, data=json.dumps({"action": "pull"}), content_type="application/json"
            )
        self.assertEqual(response.status_code, 502)
        self.connection.refresh_from_db()
        self.assertEqual(self.connection.config["material_database_snapshot"], {"stored": ["PLA"]})
