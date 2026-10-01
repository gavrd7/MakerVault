"""Bounded camera I/O. Camera targets stay on the configured printer host."""
import base64
import ipaddress
import json
import socket
import time
from io import BytesIO
from urllib.parse import urljoin, urlsplit, urlunsplit

import urllib3
from websockets.sync.client import connect as ws_connect
from websockets.exceptions import WebSocketException
from PIL import Image, UnidentifiedImageError

MOONRAKER = {"moonraker", "elegoo", "qidi", "sovol", "snapmaker", "voron"}
MODES = {"snapshot", "mjpeg", "creality_webrtc"}
MAX_IMAGE = 2 * 1024 * 1024
MAX_JSON = 256 * 1024


class CameraError(Exception):
    pass


def endpoint(connection):
    parsed = urlsplit(connection.endpoint_url)
    if not parsed.hostname:
        raise CameraError("Configure the printer connection first.")
    return parsed


def camera_url(connection, value):
    value = str(value or "").strip()
    base = endpoint(connection)
    if len(value) > 2048 or any(ord(char) < 32 for char in value) or "\\" in value:
        raise CameraError("Invalid camera URL.")
    if value.startswith("/") and not value.startswith("//"):
        # Conventional Moonraker camera paths are served by its HTTP front end.
        netloc = base.netloc if base.port != 7125 else (f"[{base.hostname}]" if ":" in base.hostname else base.hostname)
        value = urljoin(urlunsplit(("https" if base.scheme in {"https", "wss"} else "http", netloc, "/", "", "")), value)
    parsed = urlsplit(value)
    try:
        port = parsed.port
    except ValueError as exc:
        raise CameraError("Invalid camera port.") from exc
    if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password or parsed.fragment:
        raise CameraError("Use an HTTP(S) camera URL without embedded credentials or fragments.")
    if parsed.hostname.lower().rstrip(".") != base.hostname.lower().rstrip("."):
        raise CameraError("Use a camera URL on the same host as this printer connection.")
    if port is not None and not 1 <= port <= 65535:
        raise CameraError("Invalid camera port.")
    return value


def normalise_source(connection, data, source_id):
    if not isinstance(data, dict) or data.get("mode") not in MODES:
        raise CameraError("Choose JPEG snapshot, MJPEG or Creality WebRTC.")
    mode = data["mode"]
    url = camera_url(connection, data.get("url"))
    if mode == "creality_webrtc":
        if connection.adapter != "creality_local" or urlsplit(url).path != "/call/webrtc_local" or urlsplit(url).query:
            raise CameraError("Creality WebRTC requires the Creality integration and /call/webrtc_local.")
    rotation = int(data.get("rotation") or 0)
    if rotation not in {0, 90, 180, 270}:
        raise CameraError("Camera rotation must be 0, 90, 180 or 270 degrees.")
    return {"id": source_id, "name": str(data.get("name") or "Camera")[:100], "mode": mode, "url": url, "rotation": rotation, "flip_horizontal": data.get("flip_horizontal") is True, "flip_vertical": data.get("flip_vertical") is True}


def sources(connection):
    result = []
    raw = (connection.config or {}).get("cameras", [])
    if not isinstance(raw, list):
        return result
    for item in raw[:8]:
        try:
            if not isinstance(item, dict) or not isinstance(item.get("id"), str):
                continue
            result.append(normalise_source(connection, item, item["id"]))
        except (CameraError, ValueError, TypeError):
            continue
    return result


def summary(connection):
    configured = sources(connection)
    return {"configured": len(configured), "viewable": bool(connection.enabled and configured), "hardware_validated": False}


def resolve_address(host, port):
    try:
        addresses = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except OSError as exc:
        raise CameraError("Could not resolve the printer camera host.") from exc
    if not addresses:
        raise CameraError("Could not resolve the printer camera host.")
    # Pin the checked address into the socket rather than resolving twice.
    for address in addresses:
        ip = ipaddress.ip_address(address[4][0])
        if ip.is_loopback or ip.is_link_local or ip.is_multicast or ip.is_unspecified or ip.is_reserved:
            raise CameraError("Camera addresses cannot target loopback, link-local or reserved services.")
    return addresses[0][4][0]


def upstream(connection, url, *, method="GET", body=None, content_type=None):
    url = camera_url(connection, url)
    parsed = urlsplit(url)
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    address = resolve_address(parsed.hostname, port)
    headers = {"Host": parsed.netloc, "Accept": "*/*", "User-Agent": "MakerVault camera/0.9"}
    base = endpoint(connection)
    base_port = base.port or (443 if base.scheme == "https" else 80)
    # API credentials may only accompany requests to the original API origin.
    if parsed.scheme == base.scheme and port == base_port:
        key = (connection.config or {}).get("api_key")
        if key:
            headers["X-Api-Key"] = str(key)
    if content_type:
        headers["Content-Type"] = content_type
    if parsed.scheme == "https":
        pool = urllib3.HTTPSConnectionPool(address, port, server_hostname=parsed.hostname, assert_hostname=parsed.hostname, cert_reqs="CERT_REQUIRED", timeout=urllib3.Timeout(connect=2, read=3), maxsize=1)
    else:
        pool = urllib3.HTTPConnectionPool(address, port, timeout=urllib3.Timeout(connect=2, read=3), maxsize=1)
    try:
        response = pool.urlopen(method, urlunsplit(("", "", parsed.path or "/", parsed.query, "")), body=body, headers=headers, redirect=False, retries=False, preload_content=False)
        if response.status != 200:
            response.close()
            raise CameraError("Camera authentication failed." if response.status in {401, 403} else f"Camera service returned HTTP {response.status}.")
        return pool, response
    except (urllib3.exceptions.HTTPError, OSError) as exc:
        pool.close()
        raise CameraError("Camera service could not be reached securely.") from exc
    except Exception:
        pool.close()
        raise


def read_bounded(response, limit):
    data = bytearray()
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        chunk = response.read1(4096, decode_content=False)
        if not chunk:
            return bytes(data)
        data.extend(chunk)
        if len(data) > limit:
            raise CameraError("Camera response exceeded its size limit.")
    raise CameraError("Camera response timed out.")


def json_request(connection, url):
    pool, response = upstream(connection, url)
    try:
        return json.loads(read_bounded(response, MAX_JSON))
    except (ValueError, urllib3.exceptions.HTTPError) as exc:
        raise CameraError("Camera discovery returned an invalid response.") from exc
    finally:
        response.close()
        pool.close()


def discover(connection):
    base = endpoint(connection)
    rows = []
    if connection.adapter in MOONRAKER:
        payload = json_request(connection, connection.endpoint_url.rstrip("/") + "/server/webcams/list")
        rows = (payload.get("result", payload) or {}).get("webcams", [])
    elif connection.adapter == "octoprint":
        payload = json_request(connection, connection.endpoint_url.rstrip("/") + "/api/settings")
        webcam = payload.get("webcam") or {}
        rows = [{"name": "OctoPrint camera", "snapshot_url": webcam.get("snapshotUrl"), "stream_url": webcam.get("streamUrl")}]
    elif connection.adapter == "creality_local":
        host = f"[{base.hostname}]" if ":" in base.hostname else base.hostname
        return [normalise_source(connection, {"name": "K1 HTTP camera", "mode": "snapshot", "url": f"http://{host}:8080/?action=snapshot"}, "candidate-k1"), normalise_source(connection, {"name": "K2 Creality WebRTC (experimental)", "mode": "creality_webrtc", "url": f"http://{host}:8000/call/webrtc_local"}, "candidate-k2")]
    else:
        return []
    candidates = []
    for index, row in enumerate(rows[:8]):
        if not isinstance(row, dict) or row.get("enabled") is False:
            continue
        url = row.get("snapshot_url") or row.get("stream_url")
        if not url:
            continue
        try:
            # Unknown WebRTC/HLS sources cannot be silently relabelled MJPEG.
            if not row.get("snapshot_url") and row.get("service", "mjpegstreamer") not in {"mjpegstreamer", "mjpeg", "uv4l"}:
                continue
            candidates.append(normalise_source(connection, {**row, "mode": "snapshot" if row.get("snapshot_url") else "mjpeg", "url": url}, f"candidate-{index}"))
        except (CameraError, TypeError, ValueError):
            continue
    return candidates


def frame(connection, source):
    if source["mode"] not in {"snapshot", "mjpeg"}:
        raise CameraError("This source uses WebRTC video.")
    pool, response = upstream(connection, source["url"])
    try:
        content_type = response.headers.get("Content-Type", "").split(";", 1)[0].lower()
        if source["mode"] == "snapshot":
            if content_type not in {"image/jpeg", "image/png"}:
                raise CameraError("Camera did not return a JPEG or PNG image.")
            data = read_bounded(response, MAX_IMAGE)
        else:
            if content_type not in {"multipart/x-mixed-replace", "image/jpeg"}:
                raise CameraError("Camera did not return an MJPEG feed.")
            start = end = -1
            buffer = bytearray()
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline:
                chunk = response.read1(4096, decode_content=False)
                if not chunk:
                    break
                buffer.extend(chunk)
                if len(buffer) > MAX_IMAGE:
                    raise CameraError("Camera frame exceeded its size limit.")
                start = buffer.find(b"\xff\xd8")
                end = buffer.find(b"\xff\xd9", start + 2) if start >= 0 else -1
                if end >= 0:
                    break
            else:
                raise CameraError("Camera frame timed out.")
            if start < 0 or end < 0:
                raise CameraError("Camera did not provide a complete JPEG frame.")
            data = bytes(buffer[start:end + 2])
            content_type = "image/jpeg"
        with Image.open(BytesIO(data)) as image:
            if image.format not in {"JPEG", "PNG"} or image.width * image.height > 16_000_000:
                raise CameraError("Camera image dimensions or format are unsupported.")
            image.verify()
        return data, content_type
    except (urllib3.exceptions.HTTPError, OSError, UnidentifiedImageError, Image.DecompressionBombError, ValueError) as exc:
        raise CameraError("Camera frame was incomplete or invalid.") from exc
    finally:
        response.close()
        pool.close()


def creality_session(connection):
    base = endpoint(connection)
    address = resolve_address(base.hostname, base.port or 9999)
    socket_client = None
    transport = None
    features = []
    try:
        transport = socket.create_connection((address, base.port or 9999), timeout=2)
        socket_client = ws_connect(connection.endpoint_url, sock=transport, proxy=None, open_timeout=2, close_timeout=1, max_size=MAX_JSON, subprotocols=["wsslicer"])
        socket_client.send(json.dumps({"method": "get", "params": {"getToken": 1}}))
        deadline = time.monotonic() + 4
        while time.monotonic() < deadline:
            value = socket_client.recv(timeout=2)
            if len(value) > MAX_JSON:
                raise CameraError("Camera session response exceeded its size limit.")
            try:
                message = json.loads(value)
            except (ValueError, TypeError):
                continue
            if not isinstance(message, dict):
                continue
            if isinstance(message.get("features"), list):
                features = message["features"]
            token = message.get("videoToken")
            if token:
                return str(token).strip(), "videoInfo.videoEncryption" in features
    except (WebSocketException, OSError, TimeoutError):
        pass
    finally:
        if socket_client:
            socket_client.close()
        if transport:
            transport.close()
    if "videoInfo.videoEncryption" in features:
        raise CameraError("Printer did not provide the required camera token.")
    return "", False


def negotiate(connection, source, offer):
    if source["mode"] != "creality_webrtc":
        raise CameraError("This camera does not use Creality WebRTC.")
    if not isinstance(offer, str) or len(offer) > 65536 or not offer.startswith("v=0") or "m=video " not in offer or "m=application " in offer or "m=audio " in offer:
        raise CameraError("Provide a bounded video-only WebRTC offer.")
    token, protected = creality_session(connection)
    url = source["url"]
    body = {"type": "offer", "sdp": offer}
    if protected:
        parsed = urlsplit(url)
        host = f"[{parsed.hostname}]" if ":" in parsed.hostname else parsed.hostname
        url = urlunsplit((parsed.scheme, host, "/call/webrtc_local", "", ""))
        body["token"] = token
    encoded = base64.b64encode(json.dumps(body).encode("utf-8"))
    pool, response = upstream(connection, url, method="POST", body=encoded, content_type="plain/text")
    try:
        answer = json.loads(base64.b64decode(read_bounded(response, MAX_JSON).strip(), validate=True))
        if not isinstance(answer, dict) or answer.get("type") != "answer" or not isinstance(answer.get("sdp"), str) or len(answer["sdp"]) > 65536 or not answer["sdp"].startswith("v=0"):
            raise CameraError("Printer did not return a valid WebRTC answer.")
        return {"type": "answer", "sdp": answer["sdp"]}
    except (ValueError, urllib3.exceptions.HTTPError) as exc:
        raise CameraError("Printer returned an unsupported camera response. Check its firmware and camera availability.") from exc
    finally:
        response.close()
        pool.close()
