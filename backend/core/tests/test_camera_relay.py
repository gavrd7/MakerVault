import uuid
from unittest.mock import MagicMock, patch

from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase, override_settings

from core.camera_relay import (
    bridge_signature,
    bridge_source,
    ensure_stream,
    hls_master,
    hls_resource,
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

    @patch("core.camera_relay._bounded_get")
    @patch("core.camera_relay.ensure_stream", return_value="makervault_test")
    def test_hls_master_uses_loopback_go2rtc_stream(self, ensure, bounded):
        bounded.return_value = (
            b"#EXTM3U\n#EXT-X-STREAM-INF:BANDWIDTH=1000000\nhls/playlist.m3u8?id=test123\n",
            "application/vnd.apple.mpegurl",
        )
        connection_id = uuid.uuid4()
        result = hls_master(connection_id, "camera-1")
        self.assertTrue(result.startswith("#EXTM3U"))
        ensure.assert_called_once_with(connection_id, "camera-1")
        self.assertEqual(bounded.call_args.args[0], "/api/stream.m3u8")
        self.assertEqual(bounded.call_args.kwargs["params"]["src"], "makervault_test")

    @patch("core.camera_relay._bounded_get")
    @patch("core.camera_relay.ensure_stream", return_value="makervault_test")
    def test_ios_transport_uses_mpeg_ts_without_mp4_flag(self, ensure, bounded):
        bounded.return_value = (b"#EXTM3U\\n#EXT-X-STREAM-INF:BANDWIDTH=1000000\\nhls/playlist.m3u8?id=test123\\n", "application/vnd.apple.mpegurl")
        hls_master(uuid.uuid4(), "camera-1", mpeg_ts=True)
        self.assertEqual(bounded.call_args.kwargs["params"], {"src": "makervault_test"})

    @patch("core.camera_relay._bounded_get")
    def test_segment_sequence_is_forwarded_to_go2rtc(self, bounded):
        bounded.return_value = (b"segment", "video/iso.segment")
        data, _ = hls_resource("abc123", "segment.m4s", sequence="1042")
        self.assertEqual(data, b"segment")
        self.assertEqual(bounded.call_args.kwargs["params"], {"id": "abc123", "n": "1042"})
        with self.assertRaisesMessage(ValueError, "Invalid HLS segment sequence"):
            hls_resource("abc123", "segment.m4s", sequence="../test")
        with self.assertRaisesMessage(ValueError, "Invalid HLS segment sequence"):
            hls_resource("abc123", "playlist.m3u8", sequence="1042")

    @patch("core.camera_relay._bounded_get")
    def test_hls_resource_rejects_unknown_resource(self, bounded):
        with self.assertRaisesMessage(ValueError, "Unsupported camera relay resource"):
            hls_resource("abc123", "debug")
        bounded.assert_not_called()


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
        self.base = (
            f"/api/printing/printers/{self.printer.id}/connections/"
            f"{self.connection.id}/cameras/k2-camera/hls/"
        )
        self.client.force_login(self.owner)

    @patch("core.camera_views.hls_master")
    def test_owner_can_start_authenticated_hls_session(self, master):
        master.return_value = (
            "#EXTM3U\n#EXT-X-STREAM-INF:BANDWIDTH=1000000,CODECS=\"avc1.64001F\"\n"
            "hls/playlist.m3u8?id=abc123\n"
        )
        response = self.client.get(self.base + "master.m3u8")
        self.assertEqual(response.status_code, 200, response.content)
        self.assertIn(b"playlist.m3u8?id=abc123", response.content)
        self.assertNotIn(b"hls/playlist", response.content)
        master.assert_called_once_with(self.connection.pk, "k2-camera")

    @patch("core.camera_views.hls_master")
    def test_explicit_ts_master_request_is_isolated_from_default(self, master):
        master.return_value = "#EXTM3U\\n#EXT-X-STREAM-INF:BANDWIDTH=1000000\\nhls/playlist.m3u8?id=abc123\\n"
        self.assertEqual(self.client.get(self.base + "master.m3u8?format=ts").status_code, 200)
        master.assert_called_once_with(self.connection.pk, "k2-camera", mpeg_ts=True)
        master.reset_mock()
        self.assertEqual(self.client.get(self.base + "master.m3u8").status_code, 200)
        master.assert_called_once_with(self.connection.pk, "k2-camera")

    @patch("core.camera_views.hls_resource")
    @patch("core.camera_views.hls_master")
    def test_segment_uris_retain_distinct_sequence_values(self, master, resource):
        master.return_value = "#EXTM3U\\n#EXT-X-STREAM-INF:BANDWIDTH=1000000\\nhls/playlist.m3u8?id=abc123\\n"
        self.client.get(self.base + "master.m3u8")
        resource.return_value = (
            b'#EXTM3U\\n#EXT-X-MEDIA-SEQUENCE:1042\\n'
            b'#EXT-X-MAP:URI="init.mp4?id=abc123"\\n'
            b'#EXTINF:0.5,\\nsegment.m4s?id=abc123&n=1042\\n'
            b'#EXTINF:0.5,\\nsegment.m4s?id=abc123&n=1043\\n',
            "application/vnd.apple.mpegurl",
        )
        playlist = self.client.get(self.base + "playlist.m3u8?id=abc123")
        self.assertEqual(playlist.status_code, 200)
        self.assertIn(b"segment.m4s?id=abc123&n=1042", playlist.content)
        self.assertIn(b"segment.m4s?id=abc123&n=1043", playlist.content)
        self.assertNotIn(b"hls/segment.m4s", playlist.content)
        resource.return_value = (b"segment", "video/iso.segment")
        response = self.client.get(self.base + "segment.m4s?id=abc123&n=1042")
        self.assertEqual(response.status_code, 200)
        resource.assert_called_with("abc123", "segment.m4s", sequence="1042")
        denied = self.client.get(self.base + "segment.m4s?id=abc123&n=../test")
        self.assertEqual(denied.status_code, 400)

    @patch("core.camera_views.hls_resource")
    @patch("core.camera_views.hls_master")
    def test_hls_resources_require_session_created_for_same_user_and_camera(self, master, resource):
        master.return_value = "#EXTM3U\nhls/playlist.m3u8?id=abc123\n"
        self.client.get(self.base + "master.m3u8")
        resource.return_value = (
            b"#EXTM3U\n#EXT-X-MAP:URI=\"init.mp4?id=abc123\"\nsegment.m4s?id=abc123\n",
            "application/vnd.apple.mpegurl",
        )
        response = self.client.get(self.base + "playlist.m3u8?id=abc123")
        self.assertEqual(response.status_code, 200, response.content)
        self.assertIn(b"segment.m4s?id=abc123", response.content)
        resource.assert_called_once_with("abc123", "playlist.m3u8", sequence=None)

        self.client.force_login(self.other)
        denied = self.client.get(self.base + "playlist.m3u8?id=abc123")
        self.assertEqual(denied.status_code, 404)

    @patch("core.camera_views.hls_master")
    def test_expired_or_uncreated_hls_session_is_rejected(self, master):
        response = self.client.get(self.base + "segment.m4s?id=missing")
        self.assertEqual(response.status_code, 403)
        master.assert_not_called()

    @patch("core.camera_views.hls_master")
    def test_disabled_connection_never_starts_relay(self, master):
        self.connection.enabled = False
        self.connection.save(update_fields=["enabled"])
        response = self.client.get(self.base + "master.m3u8")
        self.assertEqual(response.status_code, 409)
        master.assert_not_called()

    @patch("core.camera_views.hls_master")
    def test_non_creality_source_is_rejected(self, master):
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
        response = self.client.get(self.base + "master.m3u8")
        self.assertEqual(response.status_code, 400)
        master.assert_not_called()
