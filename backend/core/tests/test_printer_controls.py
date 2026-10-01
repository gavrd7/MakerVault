import json
import uuid
from datetime import timedelta
from unittest.mock import AsyncMock, Mock, patch

from django.contrib.auth import get_user_model
from django.test import TestCase, SimpleTestCase, Client
from django.utils import timezone

from core.models import Printer, PrinterConnection, PrinterControlRequest
from core.printer_controls import PrinterControlError, dispatch_control, job_token


class PrinterControlApiTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_superuser("controls-owner", "controls@example.com", "test-password")
        self.other = get_user_model().objects.create_user("controls-other", password="test-password")
        self.printer = Printer.objects.create(owner=self.user, name="K2 test", model="K2")
        self.snapshot = {
            "online": True, "state": "printing", "job": {"file_name": "part.gcode"},
            "source_metadata": {"print_id": "job-1", "print_start_time": 1234},
            "maker_vault_job": {"job_id": "tracked-job-1"},
        }
        self.connection = PrinterConnection.objects.create(
            printer=self.printer, adapter="creality_local", endpoint_url="ws://k2.local:9999",
            controls_enabled=True, status="connected", last_seen_at=timezone.now(), last_snapshot=self.snapshot,
        )
        self.client.force_login(self.user)
        self.url = f"/api/printing/printers/{self.printer.id}/connections/{self.connection.id}/control/"
        self.payload = {"action": "pause", "request_id": str(uuid.uuid4()), "job_token": job_token(self.snapshot)}
        self.poll = patch("core.printer_controls.poll_connection", side_effect=self.refresh)
        self.send = patch("core.printer_controls.dispatch_control")
        self.poll_mock = self.poll.start()
        self.send_mock = self.send.start()
        self.addCleanup(self.poll.stop)
        self.addCleanup(self.send.stop)

    def refresh(self, connection):
        connection.last_snapshot = self.snapshot
        connection.last_seen_at = timezone.now()
        connection.save(update_fields=["last_snapshot", "last_seen_at"])
        return self.snapshot

    def post(self, **changes):
        return self.client.post(self.url, json.dumps({**self.payload, **changes}), content_type="application/json")

    def test_controls_default_off_and_config_cannot_bypass(self):
        self.assertFalse(PrinterConnection(printer=self.printer, adapter="moonraker").controls_enabled)
        self.connection.controls_enabled = False
        self.connection.config = {"controls_enabled": True}
        self.connection.save()
        self.assertEqual(self.post().status_code, 409)
        self.send_mock.assert_not_called()

    def test_success_is_sent_not_fabricated_printer_state(self):
        response = self.post()
        self.assertEqual(response.status_code, 202, response.content)
        self.assertEqual(response.json()["command"]["status"], "sent")
        self.assertEqual(response.json()["item"]["snapshot"]["state"], "printing")
        self.send_mock.assert_called_once()

    def test_dashboard_exposes_owned_source_controls_without_credentials(self):
        self.connection.config = {"access_code": "secret-access-code", "api_key": "secret-api-key"}
        self.connection.save()
        response = self.client.get("/api/dashboard/")
        self.assertEqual(response.status_code, 200)
        row = response.json()["live_printers"][0]
        self.assertEqual(row["connection_id"], str(self.connection.id))
        self.assertTrue(row["can_control"])
        self.assertEqual(row["controls"]["actions"], ["pause", "cancel"])
        self.assertEqual(row["controls"]["job_token"], job_token(self.snapshot))
        self.assertNotIn("secret-access-code", response.content.decode())
        self.assertNotIn("secret-api-key", response.content.decode())
        self.client.force_login(self.other)
        self.assertEqual(self.client.get("/api/dashboard/").json()["live_printers"], [])

    def test_dashboard_viewer_cannot_control_and_stale_job_has_no_actions(self):
        self.printer.owner = self.other
        self.printer.save()
        self.client.force_login(self.other)
        row = self.client.get("/api/dashboard/").json()["live_printers"][0]
        self.assertFalse(row["can_control"])
        self.connection.last_seen_at = timezone.now() - timedelta(seconds=61)
        self.connection.save()
        row = self.client.get("/api/dashboard/").json()["live_printers"][0]
        self.assertEqual(row["controls"]["actions"], [])

    def test_camera_metadata_does_not_advertise_a_viewable_feed(self):
        from core.api_views import _serialise_printer_connection
        self.connection.capabilities = {"camera": True, "job": True}
        self.connection.last_snapshot = {**self.snapshot, "source_metadata": {"webrtc_support": True}}
        row = _serialise_printer_connection(self.connection)
        self.assertTrue(row["camera"]["reported"])
        self.assertFalse(row["camera"]["viewable"])
        self.assertFalse(row["capabilities"]["camera"])
        self.assertTrue(self.connection.capabilities["camera"])
        self.connection.last_snapshot = {**self.snapshot, "camera_url": "rtsp://printer.local/live"}
        self.assertFalse(_serialise_printer_connection(self.connection)["camera"]["viewable"])
        self.connection.last_snapshot = self.snapshot
        self.assertFalse(_serialise_printer_connection(self.connection)["camera"]["reported"])

    def test_replay_does_not_send_again(self):
        self.assertEqual(self.post().status_code, 202)
        self.assertEqual(self.post().status_code, 202)
        self.send_mock.assert_called_once()
        self.poll_mock.assert_called_once()

    def test_uncertain_send_keeps_receipt_and_is_not_retried(self):
        self.send_mock.side_effect = PrinterControlError("Timeout", 502)
        self.assertEqual(self.post().status_code, 502)
        receipt = PrinterControlRequest.objects.get(pk=self.payload["request_id"])
        self.assertEqual(receipt.status, "unknown")
        self.assertEqual(self.post().json()["command"]["status"], "unknown")
        self.send_mock.assert_called_once()

    def test_foreign_printer_and_viewer_are_rejected(self):
        self.client.force_login(self.other)
        self.assertEqual(self.post().status_code, 404)
        self.printer.owner = self.other
        self.printer.save()
        self.assertEqual(self.post().status_code, 403)
        self.send_mock.assert_not_called()

    def test_requires_post_and_csrf(self):
        self.assertEqual(self.client.get(self.url).status_code, 405)
        csrf_client = Client(enforce_csrf_checks=True)
        csrf_client.force_login(self.user)
        self.assertEqual(csrf_client.post(self.url, self.payload).status_code, 403)
        self.send_mock.assert_not_called()

    def test_cancel_requires_explicit_confirmation(self):
        self.assertEqual(self.post(action="cancel").status_code, 400)
        self.send_mock.assert_not_called()
        self.assertEqual(self.post(action="cancel", confirmed_cancel=True).status_code, 202)

    def test_resume_requires_paused_state(self):
        self.assertEqual(self.post(action="resume").status_code, 409)
        self.send_mock.assert_not_called()

    def test_unknown_actions_and_bad_ids_are_rejected(self):
        for value in ("start_print", "gcode", "heat", "PAUSE", ""):
            self.assertEqual(self.post(action=value).status_code, 400)
        self.assertEqual(self.post(request_id="bad-id").status_code, 400)
        self.send_mock.assert_not_called()

    def test_non_object_json_is_rejected(self):
        response = self.client.post(self.url, "[]", content_type="application/json")
        self.assertEqual(response.status_code, 400)
        self.send_mock.assert_not_called()

    def test_fresh_paused_job_can_resume(self):
        self.snapshot = {**self.snapshot, "state": "paused"}
        self.connection.last_snapshot = self.snapshot
        self.connection.save()
        response = self.post(action="resume", job_token=job_token(self.snapshot))
        self.assertEqual(response.status_code, 202, response.content)
        self.send_mock.assert_called_once()

    def test_stale_disabled_and_unsupported_sources_are_rejected(self):
        for changes in (
            {"last_seen_at": timezone.now() - timedelta(seconds=61)},
            {"enabled": False},
            {"adapter": "bambu_local"},
        ):
            for key, value in changes.items():
                setattr(self.connection, key, value)
            self.connection.save()
            self.assertEqual(self.post().status_code, 409)
            self.connection.last_seen_at = timezone.now()
            self.connection.enabled = True
            self.connection.adapter = "creality_local"
        self.send_mock.assert_not_called()

    def test_changed_job_during_preflight_is_rejected(self):
        self.snapshot = {**self.snapshot, "source_metadata": {"print_id": "new-print", "print_start_time": 5678}}
        response = self.post()
        self.assertEqual(response.status_code, 409, response.content)
        self.send_mock.assert_not_called()
        self.assertEqual(PrinterControlRequest.objects.get(pk=self.payload["request_id"]).status, "rejected")

    def test_state_changed_during_preflight_is_rejected(self):
        self.snapshot = {**self.snapshot, "state": "complete"}
        self.assertEqual(self.post().status_code, 409)
        self.send_mock.assert_not_called()

    def test_recent_command_across_another_source_blocks_send(self):
        other_source = PrinterConnection.objects.create(printer=self.printer, adapter="moonraker")
        PrinterControlRequest.objects.create(connection=other_source, requested_by=self.user, action="pause", expected_job="x" * 64)
        self.assertEqual(self.post().status_code, 409)
        self.send_mock.assert_not_called()

    def test_control_opt_in_is_typed_and_adapter_scoped(self):
        url = self.url.replace("control/", "")
        response = self.client.patch(url, json.dumps({"controls_enabled": "false"}), content_type="application/json")
        self.assertEqual(response.status_code, 400)
        response = self.client.patch(url, json.dumps({"controls_enabled": False}), content_type="application/json")
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.json()["item"]["controls"]["enabled"])


class PrinterControlProtocolTests(SimpleTestCase):
    def connection(self, adapter):
        return Mock(adapter=adapter, endpoint_url="http://printer.local", config={"api_key": "private-key"})

    @patch("core.printer_controls.requests.post")
    def test_moonraker_uses_only_job_endpoints_and_requires_ack(self, post):
        post.return_value = Mock(status_code=200)
        post.return_value.json.return_value = {"result": "ok"}
        for adapter in ("moonraker", "elegoo", "qidi", "sovol", "snapmaker", "voron"):
            for action in ("pause", "resume", "cancel"):
                dispatch_control(self.connection(adapter), action)
                self.assertEqual(post.call_args.args[0], "http://printer.local/printer/print/" + action)
                self.assertEqual(post.call_args.kwargs["headers"]["X-Api-Key"], "private-key")
                self.assertFalse(post.call_args.kwargs["allow_redirects"])
        post.return_value.json.return_value = {"error": "rejected"}
        with self.assertRaises(PrinterControlError):
            dispatch_control(self.connection("moonraker"), "pause")

    @patch("core.printer_controls.requests.post")
    def test_octoprint_uses_explicit_pause_resume_never_toggle(self, post):
        post.return_value = Mock(status_code=204)
        for action in ("pause", "resume", "cancel"):
            dispatch_control(self.connection("octoprint"), action)
            expected = {"command": "cancel"} if action == "cancel" else {"command": "pause", "action": action}
            self.assertEqual(post.call_args.kwargs["json"], expected)
        post.return_value.status_code = 302
        with self.assertRaises(PrinterControlError):
            dispatch_control(self.connection("octoprint"), "pause")

    @patch("core.printer_controls.websockets.connect")
    def test_creality_wire_commands_are_exact(self, connect):
        ws = AsyncMock()
        connect.return_value.__aenter__ = AsyncMock(return_value=ws)
        connect.return_value.__aexit__ = AsyncMock(return_value=False)
        for action, params in (("pause", {"pause": 1}), ("resume", {"pause": 0}), ("cancel", {"stop": 1})):
            dispatch_control(self.connection("creality_local"), action)
            self.assertEqual(json.loads(ws.send.call_args.args[0]), {"method": "set", "params": params})

    def test_dispatch_rejects_unknown_actions_and_monitor_only_adapters(self):
        for adapter, action in (("bambu_local", "pause"), ("prusa", "cancel"), ("moonraker", "gcode")):
            with self.assertRaises(PrinterControlError):
                dispatch_control(self.connection(adapter), action)
