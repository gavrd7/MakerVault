import base64
import json
import logging
import os
import re
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, unquote, urlsplit

from django.core.management.base import BaseCommand
from django.db import close_old_connections

from core.camera_relay import valid_bridge_signature
from core.models import PrinterConnection
from core.printer_cameras import CameraError, negotiate, sources


log = logging.getLogger(__name__)
PATH_RE = re.compile(r"^/creality/([0-9a-fA-F-]{36})/([^/]+)$")
MAX_BODY = 70_000


class RelayHandler(BaseHTTPRequestHandler):
    server_version = "MakerVaultCameraRelay/1.0"

    def _send(self, status, body=b"", content_type="text/plain; charset=utf-8"):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        if body:
            self.wfile.write(body)

    def do_POST(self):
        close_old_connections()
        try:
            parsed = urlsplit(self.path)
            match = PATH_RE.fullmatch(parsed.path)
            if not match:
                self._send(404, b"Not found")
                return

            try:
                connection_id = uuid.UUID(match.group(1))
            except ValueError:
                self._send(404, b"Not found")
                return

            camera_id = unquote(match.group(2))
            if not camera_id or len(camera_id) > 128:
                self._send(404, b"Not found")
                return

            signature = (parse_qs(parsed.query).get("sig") or [""])[0]
            if not valid_bridge_signature(connection_id, camera_id, signature):
                self._send(403, b"Forbidden")
                return

            try:
                length = int(self.headers.get("Content-Length", "0"))
            except ValueError:
                self._send(400, b"Invalid request")
                return
            if length <= 0 or length > MAX_BODY:
                self._send(413, b"Request too large")
                return

            encoded = self.rfile.read(length)
            try:
                payload = json.loads(base64.b64decode(encoded.strip(), validate=True))
            except (ValueError, TypeError, json.JSONDecodeError):
                self._send(400, b"Invalid offer")
                return
            if not isinstance(payload, dict):
                self._send(400, b"Invalid offer")
                return

            connection = (
                PrinterConnection.objects.select_related("printer")
                .filter(pk=connection_id, enabled=True)
                .first()
            )
            if not connection:
                self._send(404, b"Printer source not found")
                return

            source = next((item for item in sources(connection) if item["id"] == camera_id), None)
            if not source or source.get("mode") != "creality_webrtc":
                self._send(404, b"Camera source not found")
                return

            try:
                answer = negotiate(connection, source, payload.get("sdp"))
            except CameraError as exc:
                log.warning("K2 relay negotiation failed for connection %s: %s", connection_id, exc)
                self._send(502, str(exc).encode("utf-8"))
                return

            body = base64.b64encode(json.dumps(answer, separators=(",", ":")).encode("utf-8"))
            self._send(200, body)
        finally:
            close_old_connections()

    def log_message(self, _format, *_args):
        # Do not log signed relay URLs or SDP bodies.
        return


class Command(BaseCommand):
    help = "Run MakerVault's localhost-only protected Creality camera relay bridge."

    def add_arguments(self, parser):
        parser.add_argument(
            "--host",
            default=os.environ.get("MAKERVAULT_CAMERA_RELAY_BRIDGE_HOST", "127.0.0.1"),
        )
        parser.add_argument(
            "--port",
            type=int,
            default=int(os.environ.get("MAKERVAULT_CAMERA_RELAY_BRIDGE_PORT", "1985")),
        )

    def handle(self, *args, **options):
        host = options["host"]
        port = options["port"]
        if host not in {"127.0.0.1", "::1", "localhost"}:
            raise ValueError("The camera relay bridge must bind to loopback only.")
        server = ThreadingHTTPServer((host, port), RelayHandler)
        self.stdout.write(f"MakerVault camera relay bridge listening on {host}:{port}")
        try:
            server.serve_forever(poll_interval=0.5)
        except KeyboardInterrupt:
            pass
        finally:
            server.server_close()
