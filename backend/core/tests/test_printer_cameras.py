import base64
import json
import socket
from io import BytesIO
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from PIL import Image
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.core.cache import cache
from django.test import SimpleTestCase, TestCase, Client, override_settings

from core.api_views import _serialise_printer_connection
from core.models import Printer, PrinterConnection
from core.printer_cameras import CameraError, camera_url, discover, frame, negotiate, resolve_address, upstream, creality_session, read_bounded


def jpeg():
    buffer = BytesIO()
    Image.new("RGB", (8, 8), "blue").save(buffer, "JPEG")
    return buffer.getvalue()


def response(data, content_type="image/jpeg", status=200):
    result = MagicMock(status=status, headers={"Content-Type": content_type})
    result.read1.side_effect = [data, b""]
    return result


class CameraProtocolTests(SimpleTestCase):
    def setUp(self):
        self.connection = SimpleNamespace(endpoint_url="http://printer.lan:7125", adapter="moonraker", config={"api_key": "secret"})

    def test_url_host_credentials_scheme_and_relative_resolution(self):
        self.assertEqual(camera_url(self.connection, "/webcam/?action=snapshot"), "http://printer.lan/webcam/?action=snapshot")
        for url in ("http://other.lan/snapshot", "file:///etc/passwd", "http://user:password@printer.lan/snapshot", "http://printer.lan:invalid/", "http://printer.lan/#secret", "http://printer.lan/\nsecret"):
            with self.assertRaises(CameraError):
                camera_url(self.connection, url)

    @patch("core.printer_cameras.socket.getaddrinfo")
    def test_private_printer_allowed_but_special_services_denied(self, resolve):
        for address in ("127.0.0.1", "169.254.169.254", "::1", "0.0.0.0", "224.0.0.1"):  # nosec B104 -- rejection fixtures; no bind operation
            resolve.return_value = [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (address, 80))]
            with self.assertRaises(CameraError):
                resolve_address("printer.lan", 80)
        resolve.return_value = [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("192.168.1.50", 80))]
        self.assertEqual(resolve_address("printer.lan", 80), "192.168.1.50")

    @patch("core.printer_cameras.resolve_address", return_value="192.168.1.50")
    @patch("core.printer_cameras.urllib3.HTTPConnectionPool")
    def test_socket_address_pinned_redirects_off_and_key_origin_scoped(self, pool_class, resolve):
        pool = pool_class.return_value
        pool.urlopen.return_value = response(b"{}", "application/json")
        upstream(self.connection, "http://printer.lan:7125/server/webcams/list")
        self.assertEqual(pool_class.call_args.args[0], "192.168.1.50")
        self.assertFalse(pool.urlopen.call_args.kwargs["redirect"])
        self.assertEqual(pool.urlopen.call_args.kwargs["headers"]["X-Api-Key"], "secret")
        upstream(self.connection, "http://printer.lan:8080/?action=snapshot")
        self.assertNotIn("X-Api-Key", pool.urlopen.call_args.kwargs["headers"])
        pool.urlopen.return_value.status = 302
        with self.assertRaises(CameraError):
            upstream(self.connection, "http://printer.lan:8080/")
        pool.close.assert_called()

    @patch("core.printer_cameras.json_request")
    def test_moonraker_discovery_preserves_orientation_and_skips_other_hosts(self, get):
        get.return_value = {"result": {"webcams": [
            {"name": "Nozzle", "snapshot_url": "/webcam/?action=snapshot", "rotation": 90, "flip_horizontal": True},
            {"name": "Different host", "snapshot_url": "http://other.lan/snapshot"},
            {"name": "Disabled", "enabled": False, "snapshot_url": "/off"},
            {"name": "WebRTC", "service": "webrtc", "stream_url": "/video"},
        ]}}
        rows = discover(self.connection)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["rotation"], 90)
        self.assertTrue(rows[0]["flip_horizontal"])
        self.assertEqual(rows[0]["mode"], "snapshot")

    def test_provider_registry_covers_adapters_without_claiming_playback(self):
        from core.printer_cameras import PROVIDERS, provider_info
        self.assertEqual(set(PROVIDERS), {key for key, _ in PrinterConnection.ADAPTERS})
        for adapter, _ in PrinterConnection.ADAPTERS:
            self.connection.adapter = adapter
            info = provider_info(self.connection)
            self.assertFalse(info['hardware_validated'])
            self.assertEqual('creality_webrtc' in info['modes'], adapter == 'creality_local')

    @patch('core.printer_cameras.json_request')
    def test_k1_presets_preserve_host_and_do_not_probe(self, get):
        from core.printer_cameras import setup_presets
        self.connection.endpoint_url = 'ws://[fd00::50]:9999'
        self.connection.adapter = 'creality_local'
        rows = discover(self.connection)
        self.assertEqual(len(rows), 7)
        self.assertIn('http://[fd00::50]:4408/webcam/?action=stream', [row['url'] for row in rows])
        self.assertIn('http://[fd00::50]:4409/webcam/?action=snapshot', [row['url'] for row in rows])
        self.connection.adapter = 'moonraker'
        self.assertEqual(len(setup_presets(self.connection)), 6)
        get.assert_not_called()

    @patch('core.printer_cameras.json_request')
    def test_octoprint_uses_stream_when_snapshot_is_printer_local(self, get):
        self.connection.adapter = 'octoprint'
        self.connection.endpoint_url = 'https://printer.lan/octoprint'
        get.return_value = {'webcam': {'snapshotUrl': 'http://127.0.0.1:8080/?action=snapshot', 'streamUrl': '/webcam/?action=stream', 'flipH': True, 'flipV': True, 'rotate90': True}}
        rows = discover(self.connection)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['url'], 'https://printer.lan/webcam/?action=stream')
        self.assertEqual(rows[0]['mode'], 'mjpeg')
        self.assertEqual(rows[0]['rotation'], 90)
        self.assertTrue(rows[0]['flip_horizontal'])
        self.assertTrue(rows[0]['flip_vertical'])
        get.assert_called_once_with(self.connection, 'https://printer.lan/octoprint/api/settings')

    @patch('core.printer_cameras.json_request')
    def test_prusalink_native_read_only_discovery_filters_ids(self, get):
        self.connection.adapter = 'prusa'
        self.connection.endpoint_url = 'http://printer.lan'
        get.return_value = {'camera_list': [
            {'camera_id': 'cam_A-1', 'connected': True, 'config': {'name': 'Enclosure'}},
            {'camera_id': '../settings', 'connected': True},
            {'camera_id': 'offline', 'connected': False},
        ]}
        rows = discover(self.connection)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['name'], 'Enclosure')
        self.assertEqual(rows[0]['url'], 'http://printer.lan/api/v1/cameras/cam_A-1/snap')
        get.assert_called_once_with(self.connection, 'http://printer.lan/api/v1/cameras')

    @patch('core.printer_cameras.json_request')
    def test_manufacturer_urls_are_classified_without_fetching_or_leaking(self, get):
        from core.printer_cameras import discover_result
        for adapter in ('anycubic', 'flashforge'):
            self.connection.adapter = adapter
            for url, mode in [('http://printer.lan/cam.jpg', 'snapshot'), ('http://printer.lan:8080/?action=stream', 'mjpeg')]:
                self.connection.last_snapshot = {'camera_url': url}
                rows = discover(self.connection)
                self.assertEqual(rows[0]['mode'], mode)
            for url in ('rtsp://user:private@printer.lan/video', 'http://printer.lan/video.m3u8?token=private', 'http://other.lan/cam.jpg?token=private', 'http://user:private@printer.lan/cam.jpg'):
                self.connection.last_snapshot = {'camera_url': url}
                result = discover_result(self.connection)
                self.assertEqual(result['candidates'], [])
                self.assertTrue(result['warnings'])
                self.assertNotIn('private', json.dumps(result))
        get.assert_not_called()

    @patch('core.printer_cameras.json_request')
    def test_all_moonraker_profiles_share_discovery(self, get):
        from core.printer_cameras import MOONRAKER
        get.return_value = {'result': {'webcams': [{'snapshot_url': '/webcam/?action=snapshot'}]}}
        for adapter in MOONRAKER:
            self.connection.adapter = adapter
            self.assertEqual(discover(self.connection)[0]['mode'], 'snapshot')
        self.assertEqual(get.call_count, len(MOONRAKER))

    @patch('core.printer_cameras.json_request')
    def test_manual_providers_do_not_guess_native_endpoints(self, get):
        from core.printer_cameras import discover_result
        for adapter in ('bambu_local', 'simplyprint', 'other'):
            self.connection.adapter = adapter
            self.assertEqual(discover_result(self.connection)['candidates'], [])
        get.assert_not_called()

    @patch('core.printer_cameras.json_request')
    def test_malformed_camera_lists_fail_cleanly(self, get):
        get.return_value = {'result': {'webcams': {'not': 'a list'}}}
        with self.assertRaises(CameraError):
            discover(self.connection)

    @patch("core.printer_cameras.upstream")
    def test_snapshot_and_mjpeg_return_only_valid_image_and_close(self, get):
        data = jpeg()
        for mode, content_type, payload in (("snapshot", "image/jpeg", data), ("mjpeg", "multipart/x-mixed-replace; boundary=frame", b"--frame\r\nContent-Type: image/jpeg\r\n\r\n" + data + b"\r\n--frame")):
            pool, reply = MagicMock(), response(payload, content_type)
            get.return_value = pool, reply
            image, mime = frame(self.connection, {"mode": mode, "url": "http://printer.lan/image"})
            self.assertEqual(image, data)
            self.assertEqual(mime, "image/jpeg")
            reply.close.assert_called_once()
            pool.close.assert_called_once()

    @patch("core.printer_cameras.upstream")
    def test_invalid_and_empty_frames_close_response(self, get):
        for mode, payload, mime in (("snapshot", b"<svg/>", "image/svg+xml"), ("snapshot", b"bad", "image/jpeg"), ("mjpeg", b"", "multipart/x-mixed-replace")):
            pool, reply = MagicMock(), response(payload, mime)
            get.return_value = pool, reply
            with self.assertRaises(CameraError):
                frame(self.connection, {"mode": mode, "url": "http://printer.lan/image"})
            reply.close.assert_called_once()

    def test_response_size_limit(self):
        with self.assertRaises(CameraError):
            read_bounded(response(b"x" * 20), 10)

    @patch("core.printer_cameras.time.monotonic", side_effect=[0, 0, 6])
    def test_response_deadline(self, clock):
        with self.assertRaises(CameraError):
            read_bounded(response(b"x"), 100)

    @patch("core.printer_cameras.creality_session")
    @patch("core.printer_cameras.upstream")
    def test_legacy_and_protected_webrtc_encodings_hide_token(self, get, session):
        answer = {"type": "answer", "sdp": "v=0\r\nm=video 9 UDP/TLS/RTP/SAVPF 96\r\n"}
        source = {"mode": "creality_webrtc", "url": "http://printer.lan:8000/call/webrtc_local"}
        for protected in (False, True):
            session.return_value = "secret-camera-token", protected
            pool, reply = MagicMock(), response(base64.b64encode(json.dumps(answer).encode()), "text/plain")
            get.return_value = pool, reply
            result = negotiate(self.connection, source, answer["sdp"])
            self.assertEqual(result, answer)
            sent = json.loads(base64.b64decode(get.call_args.kwargs["body"]))
            self.assertEqual("token" in sent, protected)
            self.assertEqual(get.call_args.args[1], "http://printer.lan/call/webrtc_local" if protected else source["url"])
            self.assertNotIn("secret-camera-token", json.dumps(result))
            reply.close.assert_called_once()

    @patch("core.printer_cameras.creality_session")
    def test_data_channel_offer_is_rejected_before_network(self, session):
        with self.assertRaises(CameraError):
            negotiate(self.connection, {"mode": "creality_webrtc"}, "v=0\r\nm=video 9 RTP 96\r\nm=application 9 UDP\r\n")
        session.assert_not_called()

    @patch("core.printer_cameras.resolve_address", return_value="192.168.1.50")
    @patch("core.printer_cameras.socket.create_connection")
    @patch("core.printer_cameras.ws_connect")
    def test_video_token_socket_is_closed(self, connect, transport, resolve):
        self.connection.endpoint_url = "ws://printer.lan:9999"
        sock = connect.return_value
        sock.recv.side_effect = [json.dumps({"features": ["videoInfo.videoEncryption"]}), json.dumps({"videoToken": "token"})]
        self.assertEqual(creality_session(self.connection), ("token", True))
        self.assertEqual(json.loads(sock.send.call_args.args[0]), {"method": "get", "params": {"getToken": 1}})
        sock.close.assert_called_once()


@override_settings(CACHES={"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}})
class CameraApiTests(TestCase):
    def setUp(self):
        cache.clear()
        self.owner = get_user_model().objects.create_user("camera-owner")
        self.other = get_user_model().objects.create_user("camera-other")
        self.owner.user_permissions.add(Permission.objects.get(codename="change_printer"))
        self.printer = Printer.objects.create(owner=self.owner, name="K1")
        self.connection = PrinterConnection.objects.create(printer=self.printer, adapter="creality_local", endpoint_url="ws://printer.lan:9999", config={"cameras": [{"id": "cam1", "name": "Camera", "url": "http://printer.lan:8080/?action=snapshot&token=private", "mode": "snapshot"}]})
        self.root = f"/api/printing/printers/{self.printer.id}/connections/{self.connection.id}/cameras/"
        self.client.force_login(self.owner)

    @patch("core.camera_views.frame", return_value=(b"jpeg", "image/jpeg"))
    def test_owner_media_private_headers_and_other_owner_denied(self, get):
        result = self.client.get(self.root + "cam1/media/")
        self.assertEqual(result.status_code, 200)
        self.assertIn("no-store", result["Cache-Control"])
        self.assertEqual(result["Cross-Origin-Resource-Policy"], "same-origin")
        self.client.force_login(self.other)
        self.assertEqual(self.client.get(self.root + "cam1/media/").status_code, 404)
        self.assertEqual(get.call_count, 1)

    @patch("core.camera_views.frame")
    def test_disabled_source_never_contacts_camera(self, get):
        self.connection.enabled = False
        self.connection.save()
        self.assertEqual(self.client.get(self.root + "cam1/media/").status_code, 409)
        get.assert_not_called()

    def test_config_and_diagnostics_omit_camera_urls_and_tokens(self):
        self.connection.last_snapshot = {"camera_url": "rtsp://user:private@printer.lan/video"}
        result = _serialise_printer_connection(self.connection)
        self.assertNotIn("private", json.dumps(result))
        self.assertTrue(result["camera"]["reported"])
        self.assertEqual(self.connection.last_snapshot["camera_url"], "rtsp://user:private@printer.lan/video")
        self.assertNotIn("cameras", result["config"])
        self.assertTrue(result["camera"]["viewable"])
        self.owner.user_permissions.clear()
        result = self.client.get(self.root).json()
        self.assertNotIn("url", result["rows"][0])
        self.assertFalse(result["can_edit"])

    @patch("core.printer_cameras.upstream")
    def test_provider_setup_and_discovery_are_scoped_and_do_not_probe_presets(self, upstream):
        setup = self.client.get(self.root).json()
        self.assertEqual(setup["provider"]["id"], "creality")
        self.assertEqual(len(setup["presets"]), 6)
        result = self.client.post(self.root + "discover/", {}, content_type="application/json")
        self.assertEqual(result.status_code, 200)
        self.assertEqual(len(result.json()["candidates"]), 7)
        self.owner.user_permissions.clear()
        self.assertEqual(self.client.get(self.root).json()["presets"], [])
        self.assertEqual(self.client.post(self.root + "discover/", {}, content_type="application/json").status_code, 403)
        upstream.assert_not_called()

    def test_last_saved_camera_is_preview_and_selection_is_persistent(self):
        from core.printer_cameras import summary
        result = self.client.post(self.root, {"mode": "snapshot", "url": "http://printer.lan/new?token=private", "name": "New"}, content_type="application/json")
        self.assertEqual(result.status_code, 200)
        self.connection.refresh_from_db()
        latest = summary(self.connection)
        self.assertEqual(latest["preview"]["name"], "New")
        self.assertNotIn("url", latest["preview"])
        self.assertNotIn("private", json.dumps(latest))
        self.assertTrue(latest["configured_at"])
        selected = self.client.patch(self.root, {"id": "cam1"}, content_type="application/json")
        self.assertEqual(selected.status_code, 200)
        self.connection.refresh_from_db()
        self.assertEqual(summary(self.connection)["preview"]["id"], "cam1")
        self.client.delete(self.root, {"id": "cam1"}, content_type="application/json")
        self.connection.refresh_from_db()
        self.assertEqual(summary(self.connection)["preview"]["name"], "New")

    def test_preview_selection_rejects_missing_camera_and_other_owner(self):
        self.assertEqual(self.client.patch(self.root, {"id": "missing"}, content_type="application/json").status_code, 404)
        self.client.force_login(self.other)
        self.assertEqual(self.client.patch(self.root, {"id": "cam1"}, content_type="application/json").status_code, 404)
        self.client.force_login(self.owner)
        self.owner.user_permissions.clear()
        self.assertEqual(self.client.patch(self.root, {"id": "cam1"}, content_type="application/json").status_code, 403)

    def test_setup_permission_csrf_and_host_validation(self):
        self.assertEqual(self.client.post(self.root, {"mode": "snapshot", "url": "http://other.lan/image"}, content_type="application/json").status_code, 400)
        csrf_client = Client(enforce_csrf_checks=True)
        csrf_client.force_login(self.owner)
        self.assertEqual(csrf_client.post(self.root + "cam1/media/", {}, content_type="application/json").status_code, 403)
        self.owner.user_permissions.clear()
        self.assertEqual(self.client.post(self.root, {}, content_type="application/json").status_code, 403)

    def test_setup_and_remove_have_no_camera_io(self):
        with patch("core.printer_cameras.upstream") as get:
            result = self.client.post(self.root, {"mode": "snapshot", "url": "http://printer.lan:8080/image", "name": "Second"}, content_type="application/json")
            self.assertEqual(result.status_code, 200, result.content)
            self.assertEqual(len(self.client.get(self.root).json()["rows"]), 2)
            self.client.delete(self.root, {"id": "cam1"}, content_type="application/json")
            self.assertEqual(len(self.client.get(self.root).json()["rows"]), 1)
            get.assert_not_called()

    @patch("core.camera_views.frame")
    def test_overlapping_owner_requests_are_limited(self, get):
        cache.add(f"camera-request:{self.owner.pk}", "busy", timeout=20)
        self.assertEqual(self.client.get(self.root + "cam1/media/").status_code, 502)
        get.assert_not_called()
