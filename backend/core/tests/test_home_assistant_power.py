import json
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.test import TestCase, SimpleTestCase
from django.utils import timezone

from core.home_assistant_power import (
    HomeAssistantPowerError, decrypt_token, encrypt_token, printer_is_busy,
    validate_url,
)
from core.models import Printer, PrintingIntegrationSetting


class HomeAssistantPowerUnitTests(SimpleTestCase):
    def test_token_is_encrypted_and_invalid_ciphertext_is_rejected(self):
        token = "secret-home-assistant-long-lived-token"
        stored = encrypt_token(token)
        self.assertNotIn(token, stored)
        self.assertEqual(decrypt_token({"encrypted_token": stored}), token)
        with self.assertRaises(HomeAssistantPowerError):
            decrypt_token({"encrypted_token": "corrupted"})

    def test_arbitrary_public_or_metadata_hosts_cannot_be_set(self):
        for url in ("http://example.com", "https://203.0.113.10",
                    "http://169.254.169.254", "file:///etc/passwd",
                    "http://user:pass@192.168.1.4:8123",
                    "http://192.168.1.4:8123/api/",
                    "http://192.168.1.4:8123/?token=x"):
            with self.subTest(url=url):
                with self.assertRaises(HomeAssistantPowerError):
                    validate_url(url)

    def test_private_address_is_accepted(self):
        self.assertEqual(validate_url("http://192.168.1.4:8123"),
                         "http://192.168.1.4:8123")

    @patch("core.home_assistant_power.socket.getaddrinfo")
    def test_plain_http_hostname_rejected_before_dns_lookup(self, dns):
        with self.assertRaisesRegex(HomeAssistantPowerError, "private IP address"):
            validate_url("http://homeassistant.local:8123")
        dns.assert_not_called()

    @patch("core.home_assistant_power.socket.getaddrinfo")
    def test_public_https_reverse_proxy_domain_is_accepted(self, dns):
        dns.return_value = [
            (2, 1, 6, "", ("104.21.70.99", 443)),
            (2, 1, 6, "", ("172.67.215.116", 443)),
        ]
        self.assertEqual(
            validate_url("https://hass.example.org/"),
            "https://hass.example.org",
        )
        with self.assertRaisesRegex(HomeAssistantPowerError, "HTTPS"):
            validate_url("http://hass.example.org")

    @patch("core.home_assistant_power.socket.getaddrinfo")
    def test_mixed_public_private_dns_is_refused(self, dns):
        dns.return_value = [
            (2, 1, 6, "", ("192.168.1.5", 443)),
            (2, 1, 6, "", ("104.21.70.99", 443)),
        ]
        with self.assertRaisesRegex(HomeAssistantPowerError, "mixed"):
            validate_url("https://hass.example.org")

    @patch("core.home_assistant_power.switch_state")
    @patch("core.home_assistant_power.ha_request")
    def test_successful_service_call_does_not_require_immediate_state_change(self, request, read_state):
        from core.home_assistant_power import set_switch

        setting = object()
        self.assertEqual(set_switch(setting, "switch.printer_a", "off"), "off")
        request.assert_called_once_with(
            setting, "POST", "/api/services/switch/turn_off",
            body={"entity_id": "switch.printer_a"},
        )
        read_state.assert_not_called()

    def test_live_active_print_prevents_power_off(self):
        printer = SimpleNamespace(
            print_jobs=SimpleNamespace(filter=lambda **kw: SimpleNamespace(exists=lambda: False)),
            live_connections=SimpleNamespace(filter=lambda **kw: [
                SimpleNamespace(last_snapshot={"state": "printing"})]),
        )
        self.assertTrue(printer_is_busy(printer))


    def test_unknown_or_stale_live_telemetry_blocks_power_off(self):
        now = timezone.now()
        def printer_with_snapshot(snapshot, checked, status="connected"):
            return SimpleNamespace(
                print_jobs=SimpleNamespace(filter=lambda **kw: SimpleNamespace(exists=lambda: False)),
                live_connections=SimpleNamespace(filter=lambda **kw: [SimpleNamespace(
                    last_snapshot=snapshot, status=status,
                    last_checked_at=checked, poll_interval_seconds=30,
                )]),
            )
        self.assertTrue(printer_is_busy(printer_with_snapshot({}, None)))
        self.assertTrue(printer_is_busy(printer_with_snapshot(
            {"state": "idle"}, now - timedelta(minutes=10))))
        self.assertTrue(printer_is_busy(printer_with_snapshot(
            {"state": "idle"}, now, status="disconnected")))
        self.assertFalse(printer_is_busy(printer_with_snapshot({"state": "idle"}, now)))

    def test_stale_print_history_does_not_override_fresh_idle_telemetry(self):
        now = timezone.now()
        active_history = SimpleNamespace(filter=lambda **kw: SimpleNamespace(exists=lambda: True))
        def printer(connection):
            return SimpleNamespace(
                print_jobs=active_history,
                live_connections=SimpleNamespace(filter=lambda **kw: [connection]),
            )

        connection = SimpleNamespace(
            last_snapshot={"state": "idle", "job": {"state": "complete"}},
            status="connected", last_checked_at=now, poll_interval_seconds=30,
        )
        self.assertFalse(printer_is_busy(printer(connection)))
        connection.last_checked_at = now - timedelta(minutes=10)
        self.assertTrue(printer_is_busy(printer(connection)))
        connection.last_checked_at = now
        connection.last_snapshot = {"state": "idle", "job": {"state": "printing"}}
        self.assertTrue(printer_is_busy(printer(connection)))


class HomeAssistantPowerApiTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.owner = User.objects.create_superuser(
            "power-owner", "power-owner@example.test", "test-pass")
        self.other = User.objects.create_user(
            "power-other", password="test-pass")
        self.printer = Printer.objects.create(
            owner=self.owner, name="Printer A", model="Test FDM")
        self.integration = PrintingIntegrationSetting.objects.create(
            owner=self.owner, provider="homeassistant", enabled=True,
            endpoint_url="http://192.168.1.4:8123",
            status="ready", config={"encrypted_token": encrypt_token("test-token-12345")},
        )
        self.client.force_login(self.owner)
        self.power_url = "/api/printing/printers/" + str(self.printer.pk) + "/power/"
        self.assignment_url = self.power_url + "assignment/"

    def post(self, url, data, method="post"):
        return getattr(self.client, method)(
            url, json.dumps(data), content_type="application/json")

    def test_hidden_when_not_assigned_or_disabled(self):
        self.assertEqual(self.client.get(self.power_url).json(), {"available": False})
        self.assertEqual(self.post(self.power_url, {"action": "on"}).status_code, 404)
        self.integration.enabled = False
        self.integration.save()
        self.assertEqual(self.client.get(self.power_url).json(), {"available": False})

    def test_settings_are_owner_only_and_never_leak_token(self):
        self.assertNotIn("encrypted_token", str(self.client.get(
            "/api/settings/printing-integrations/").content))
        settings = self.client.get("/api/settings/home-assistant/")
        self.assertEqual(settings.status_code, 200)
        self.assertTrue(settings.json()["item"]["token_configured"])
        self.assertNotIn("encrypted_token", str(settings.content))
        self.assertEqual(self.post(
            "/api/settings/printing-integrations/homeassistant/",
            {"endpoint_url": "http://169.254.169.254"}, method="patch").status_code, 409)
        self.client.force_login(self.other)
        self.assertEqual(self.client.get("/api/settings/home-assistant/").status_code, 403)
        self.assertEqual(self.client.get(self.assignment_url).status_code, 403)
        self.assertEqual(self.client.get(self.power_url).status_code, 404)

    @patch("core.home_assistant_api.get_switches")
    def test_assigned_switch_can_be_changed_only_by_owner(self, switches):
        switches.return_value = [
            {"entity_id": "switch.printer_a", "name": "Printer", "state": "off"}]
        result = self.post(self.assignment_url, {"entity_id": "switch.printer_a"}, method="patch")
        self.assertEqual(result.status_code, 200, result.content)
        self.printer.refresh_from_db()
        self.assertEqual(self.printer.profile_data["ha_power_entity"], "switch.printer_a")
        self.client.force_login(self.other)
        self.assertEqual(self.post(self.assignment_url,
                                  {"entity_id": "switch.printer_a"}, method="patch").status_code, 403)

    @patch("core.home_assistant_api.switch_state", return_value="off")
    @patch("core.home_assistant_api.set_switch", return_value="on")
    def test_explicit_turn_on_and_verified_state(self, switch, state):
        self.printer.profile_data = {"ha_power_entity": "switch.printer_a"}
        self.printer.save()
        self.assertEqual(self.client.get(self.power_url).json(),
                         {"available": True, "state": "off"})
        result = self.post(self.power_url, {"action": "on"})
        self.assertEqual(result.status_code, 200, result.content)
        self.assertEqual(result.json()["state"], "on")
        switch.assert_called_once_with(self.integration, "switch.printer_a", "on")

    @patch("core.home_assistant_api.switch_state", side_effect=HomeAssistantPowerError("HA unavailable"))
    def test_unknown_switch_state_still_returns_assigned_control(self, state):
        self.printer.profile_data = {"ha_power_entity": "switch.printer_a"}
        self.printer.save()
        result = self.client.get(self.power_url)
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.json(), {"available": True, "state": "unknown"})

    @patch("core.home_assistant_api.printer_is_busy", return_value=True)
    @patch("core.home_assistant_api.set_switch")
    def test_turn_off_blocked_when_busy(self, switch, busy):
        self.printer.profile_data = {"ha_power_entity": "switch.printer_a"}
        self.printer.save()
        self.assertEqual(self.post(self.power_url, {"action": "off"}).status_code, 400)
        self.assertEqual(self.post(self.power_url, {"action": "off", "confirm": True}).status_code, 409)
        switch.assert_not_called()
