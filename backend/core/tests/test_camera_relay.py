import os
import uuid
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase, override_settings

from core.camera_relay import (
    bridge_signature,
    bridge_source,
    ensure_stream,
    relay_offer,
    rewrite_answer_candidates,
    stream_name,
    valid_bridge_signature,
)
from core.models import Printer, PrinterConnection


@override_settings(SECRET_KEY="relay-test-secret")
class CameraRelayHelperTests(SimpleTestCase):
    def test_bridge_signature_is_scoped_and_secret_is_not_exposed(self):
        connection_id = uuid.uuid4()
        camera_id = "camera-1"
        signature = bridge_signature(connection_id, camera_id)
        self.assertTrue(valid_bridge_signature(connection_id, camera_id, signature))
        self.assertFalse(valid_bridge_signature(connection_id, "camera-2", signature))
        source = bridge_source(connection_id, camera_id)
        self.assertIn("127.0.0.1:1985", source)
        self.assertIn("#format=creality", source)
        self.assertNotIn("relay-test-secret", source)

    @patch("core.camera_relay._SESSION.patch")
    def test_stream_registration_is_idempotent_patch(self, request):
        request.return_value = MagicMock(status_code=200)
        connection_id = uuid.uuid4()
        name = ensure_stream(connection_id, "camera-1")
        self.assertEqual(name, stream_name(connection_id, "camera-1"))
        self.assertEqual(request.call_count, 1)
        kwargs = request.call_args.kwargs
        self.assertEqual(kwargs["params"]["name"], name)
        self.assertIn("#format=creality", kwargs["params"]["src"])

    @patch.dict(os.environ, {"MAKERVAULT_CAMERA_RELAY_CANDIDATE": "192.168.1.50"}, clear=False)
    def test_loopback_ice_candidate_is_rewritten_for_browser(self):
        request = SimpleNamespace(get_host=lambda: "maker.example:8765")
        answer = (
            "v=0\r\n"
            "a=candidate:1 1 udp 2130706431 127.0.0.1 8555 typ host\r\n"
        )
        rewritten = rewrite_answer_candidates(answer, request)
        self.assertIn("192.168.1.50 8555 typ host", rewritten)
        self.assertNotIn("127.0.0.1 8555", rewritten)

    @patch.dict(os.environ, {"MAKERVAULT_CAMERA_RELAY_CANDIDATE": "192.168.1.50"}, clear=False)
    @patch("core.camera_relay._SESSION.post")
    @patch("core.camera_relay.ensure_stream", return_value="makervault_test")
    def test_relay_offer_returns_browser_reachable_answer(self, ensure, request_post):
        response = MagicMock(status_code=200)
        response.json.return_value = {
            "type": "answer",
            "sdp": "v=0\r\na=candidate:1 1 udp 1 127.0.0.1 8555 typ host\r\n",
        }
        request_post.return_value = response
        request = SimpleNamespace(get_host=lambda: "192.168.1.50:8765")
        result = relay_offer(
            request,
            uuid.uuid4(),
            "camera-1",
            "v=0\r\nm=video 9 UDP/TLS/RTP/SAVPF 96\r\n",
        )
        self.assertEqual(result["type"], "answer")
        self.assertIn("192.168.1.50 8555", result["sdp"])
        self.assertEqual(request_post.call_args.kwargs["json"]["type"], "offer")


@override_settings(CACHES={"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}})
class CameraRelayApiTests(TestCase):
    def setUp(self):
        self.owner = get_user_model().objects.create_user("relay-owner")
        self.other = get_user_model().objects.create_user("relay-other")
        self.printer = Printer.objects.create(owner=self.owner, name="K2")
        self.connection = PrinterConnection.objects.create(
            printer=self.printer,
            adapter="creality_local",
            endpoint_url="ws://printer.lan:9999",
            enabled=True,
            config={
                "cameras": [
                    {
                        "id": "k2-camera",
                        "name": "K2 camera",
                        "mode": "creality_webrtc",
                        "url": "http://printer.lan:8000/call/webrtc_local",
                        "rotation": 0,
                        "flip_horizontal": False,
                        "flip_vertical": False,
                    }
                ],
                "camera_default_id": "k2-camera",
            },
        )
        self.url = (
            f"/api/printing/printers/{self.printer.id}/connections/"
            f"{self.connection.id}/cameras/k2-camera/relay/"
        )
        self.client.force_login(self.owner)

    @patch("core.camera_views.relay_offer")
    def test_owner_can_negotiate_saved_creality_source(self, relay):
        relay.return_value = {
            "type": "answer",
            "sdp": "v=0\r\nm=video 9 UDP/TLS/RTP/SAVPF 96\r\n",
        }
        response = self.client.post(
            self.url,
            {"sdp": "v=0\r\nm=video 9 UDP/TLS/RTP/SAVPF 96\r\n"},
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200, response.content)
        relay.assert_called_once()

    @patch("core.camera_views.relay_offer")
    def test_other_owner_cannot_access_relay(self, relay):
        self.client.force_login(self.other)
        response = self.client.post(
            self.url,
            {"sdp": "v=0\r\nm=video 9 UDP/TLS/RTP/SAVPF 96\r\n"},
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 404)
        relay.assert_not_called()

    @patch("core.camera_views.relay_offer")
    def test_disabled_connection_never_starts_relay(self, relay):
        self.connection.enabled = False
        self.connection.save(update_fields=["enabled"])
        response = self.client.post(
            self.url,
            {"sdp": "v=0\r\nm=video 9 UDP/TLS/RTP/SAVPF 96\r\n"},
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 409)
        relay.assert_not_called()

    @patch("core.camera_views.relay_offer")
    def test_non_creality_source_is_rejected(self, relay):
        config = dict(self.connection.config)
        config["cameras"] = [
            {
                "id": "k2-camera",
                "name": "Snapshot",
                "mode": "snapshot",
                "url": "http://printer.lan:8000/snapshot",
                "rotation": 0,
                "flip_horizontal": False,
                "flip_vertical": False,
            }
        ]
        self.connection.config = config
        self.connection.save(update_fields=["config"])
        response = self.client.post(
            self.url,
            {"sdp": "v=0\r\nm=video 9 UDP/TLS/RTP/SAVPF 96\r\n"},
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 400)
        relay.assert_not_called()
