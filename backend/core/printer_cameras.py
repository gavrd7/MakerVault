"""Bounded camera I/O. Camera targets stay on the configured printer host."""
import base64
import ipaddress
import json
import re
import socket
import time
from io import BytesIO
from urllib.parse import parse_qs, urljoin, urlsplit, urlunsplit

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
    parsed_url = urlsplit(url)
    if mode == "creality_webrtc":
        if connection.adapter != "creality_local" or parsed_url.path != "/call/webrtc_local" or parsed_url.query:
            raise CameraError("Creality WebRTC requires the Creality integration and /call/webrtc_local.")
    elif parsed_url.path == "/call/webrtc_local":
        raise CameraError("The /call/webrtc_local endpoint must use the Creality WebRTC feed type.")
    rotation = int(data.get("rotation") or 0)
    if rotation not in {0, 90, 180, 270}:
        raise CameraError("Camera rotation must be 0, 90, 180 or 270 degrees.")
    return {"id": source_id, "name": str(data.get("name") or "Camera")[:100], "mode": mode, "url": url, "rotation": rotation, "flip_horizontal": data.get("flip_horizontal") is True, "flip_vertical": data.get("flip_vertical") is True}


def sources(connection):
    result = []
    positions = {}
    config = connection.config or {}
    raw = config.get("cameras", [])
    selected_id = str(config.get("camera_default_id") or "")
    if not isinstance(raw, list):
        return result
    for item in raw[:8]:
        try:
            if not isinstance(item, dict) or not isinstance(item.get("id"), str):
                continue
            normalised = normalise_source(connection, item, item["id"])
            signature = (normalised["mode"], normalised["url"])
            if signature in positions:
                # Old builds could append the same discovered feed repeatedly.
                # Prefer the duplicate already selected for previews, otherwise
                # retain the first stable camera ID.
                if normalised["id"] == selected_id:
                    result[positions[signature]] = normalised
                continue
            positions[signature] = len(result)
            result.append(normalised)
        except (CameraError, ValueError, TypeError):
            continue
    return result


def summary(connection):
    configured = sources(connection)
    selected = next((row for row in configured if row["id"] == (connection.config or {}).get("camera_default_id")), configured[-1] if configured else None)
    preview = {key: value for key, value in selected.items() if key != "url"} if selected else None
    return {"configured": len(configured), "viewable": bool(connection.enabled and configured), "hardware_validated": False, "preview": preview, "configured_at": (connection.config or {}).get("camera_configured_at", "")}


# Discovery is independent of playback: new providers return the same validated
# source contract and reuse the bounded, owner-scoped transports below.
PROVIDERS = {
    **{key: ("moonraker", "Read cameras configured in Moonraker. Klipper itself does not serve camera images.") for key in MOONRAKER},
    "octoprint": ("octoprint", "Read the default webcam settings. The API key needs Settings Read permission."),
    "creality_local": ("creality", "Choose the K1 route that works in your installation, or experimental K2 WebRTC. Presets do not verify playback. If Creality Cloud works but K1 HTTP does not, check that the printer's local mjpg_streamer service is running."),
    "prusa": ("prusalink", "Read local PrusaLink cameras where its camera API is available. Requires an API key; Prusa Connect cloud cameras are not imported."),
    "anycubic": ("reported", "Use a supported camera URL reported by the printer. RTSP needs a media relay, which is not included yet."),
    "flashforge": ("reported", "Use a supported camera URL reported by the printer. Opaque or unsupported stream formats require manual setup or a future relay."),
    "bambu_local": ("manual", "Native Bambu camera transport is not implemented. A separately provided same-host HTTP image feed can be configured manually."),
    "simplyprint": ("manual", "SimplyPrint cloud camera access is not implemented. Use a local Moonraker or OctoPrint integration where the printer supports it."),
    "other": ("manual", "Enter a same-host HTTP snapshot or MJPEG URL, or add a Moonraker / OctoPrint integration where available."),
}


def provider_info(connection):
    kind, guidance = PROVIDERS.get(connection.adapter, PROVIDERS["other"])
    return {"id": kind, "guidance": guidance, "modes": ["snapshot", "mjpeg"] + (["creality_webrtc"] if connection.adapter == "creality_local" else []), "hardware_validated": False}


def k1_presets(connection):
    base = endpoint(connection)
    host = f"[{base.hostname}]" if ":" in base.hostname else base.hostname
    routes = [("K1 direct", 8080, "/"), ("K1 Helper Script / Fluidd", 4408, "/webcam/"), ("K1 Helper Script / Mainsail", 4409, "/webcam/")]
    return [normalise_source(connection, {"name": name + " · " + mode, "mode": mode, "url": f"http://{host}:{port}{path}?action={action}"}, f"preset-k1-{port}-{mode}") for name, port, path in routes for mode, action in (("mjpeg", "stream"), ("snapshot", "snapshot"))]


def setup_presets(connection):
    try:
        return k1_presets(connection) if connection.adapter in {"creality_local", "moonraker"} else []
    except (CameraError, ValueError):
        return []


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
    """Compatibility helper for callers interested only in usable candidates."""
    return discover_result(connection)["candidates"]


def discover_result(connection):
    base = endpoint(connection)
    kind = provider_info(connection)["id"]
    rows, warnings = [], []
    api = connection.endpoint_url.rstrip("/")
    if kind == "moonraker":
        payload = json_request(connection, api + "/server/webcams/list")
        rows = (payload.get("result", payload) or {}).get("webcams", [])
    elif kind == "octoprint":
        payload = json_request(connection, api + "/api/settings")
        webcam = payload.get("webcam") or {}
        rows = [{"name": "OctoPrint camera", "snapshot_url": webcam.get("snapshotUrl"), "stream_url": webcam.get("streamUrl"), "flip_horizontal": webcam.get("flipH"), "flip_vertical": webcam.get("flipV"), "rotation": 90 if webcam.get("rotate90") else 0}]
    elif kind == "prusalink":
        payload = json_request(connection, api + "/api/v1/cameras")
        cameras = payload.get("camera_list", [])
        if not isinstance(cameras, list):
            raise CameraError("PrusaLink returned an invalid camera list.")
        for camera in cameras[:8]:
            if not isinstance(camera, dict) or camera.get("connected") is not True:
                continue
            camera_id = camera.get("camera_id")
            # IDs are path segments, never arbitrary upstream paths or URLs.
            if not isinstance(camera_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", camera_id):
                warnings.append("A PrusaLink camera has an unsupported identifier.")
                continue
            config = camera.get("config") or {}
            rows.append({"name": config.get("name", "PrusaLink camera") if isinstance(config, dict) else "PrusaLink camera", "snapshot_url": api + f"/api/v1/cameras/{camera_id}/snap"})
    elif kind == "creality":
        host = f"[{base.hostname}]" if ":" in base.hostname else base.hostname
        candidates = k1_presets(connection)
        candidates.append(normalise_source(connection, {"name": "K2 Creality WebRTC (experimental)", "mode": "creality_webrtc", "url": f"http://{host}:8000/call/webrtc_local"}, "candidate-k2"))
        return {"candidates": candidates, "warnings": [], "provider": provider_info(connection)}
    elif kind == "reported":
        snapshot = getattr(connection, "last_snapshot", {}) or {}
        url = snapshot.get("camera_url") if isinstance(snapshot, dict) else None
        if url:
            parsed = urlsplit(str(url))
            action = parse_qs(parsed.query).get("action", [""])[0].lower()
            path = parsed.path.lower()
            if parsed.scheme not in {"http", "https"}:
                warnings.append("The printer reports a non-HTTP camera stream. A media relay is required; native playback is not implemented yet.")
            elif path.endswith((".jpg", ".jpeg", ".png", "/snapshot", "/snap")) or action == "snapshot":
                rows = [{"name": "Manufacturer camera", "snapshot_url": url}]
            elif path.endswith((".mjpg", ".mjpeg")) or action == "stream":
                rows = [{"name": "Manufacturer camera", "stream_url": url}]
            else:
                warnings.append("The printer reports a camera URL with an unknown format. Enter a verified snapshot or MJPEG URL manually.")
        else:
            warnings.append("No camera URL was reported by the latest printer status. Refresh monitoring or configure a verified feed manually.")
    if not isinstance(rows, list):
        raise CameraError("Camera discovery returned an invalid camera list.")
    candidates = []
    for index, row in enumerate(rows[:8]):
        if not isinstance(row, dict) or row.get("enabled") is False:
            continue
        # Prefer snapshots but allow a usable stream when its snapshot is local
        # to the printer (e.g. OctoPrint's localhost snapshot configuration).
        for key, mode in (("snapshot_url", "snapshot"), ("stream_url", "mjpeg")):
            url = row.get(key)
            if not url:
                continue
            if mode == "mjpeg" and row.get("service", "mjpegstreamer") not in {"mjpegstreamer", "mjpeg", "uv4l"}:
                warnings.append("A camera uses an unsupported stream format. Configure its HTTP snapshot if available.")
                continue
            try:
                candidates.append(normalise_source(connection, {**row, "mode": mode, "url": url}, f"candidate-{index}"))
                break
            except (CameraError, TypeError, ValueError):
                warnings.append("A camera URL or orientation was rejected. Use a valid same-host HTTP URL without embedded credentials.")
    return {"candidates": candidates, "warnings": list(dict.fromkeys(warnings)), "provider": provider_info(connection)}


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


def diagnose_source(connection, source):
    """Run bounded, secret-free connectivity checks for one configured camera source."""
    mode = source.get("mode")
    if mode in {"snapshot", "mjpeg"}:
        data, content_type = frame(connection, source)
        return {
            "ok": True,
            "mode": mode,
            "checks": [
                {
                    "id": "camera",
                    "ok": True,
                    "detail": f"Camera returned {content_type} ({len(data)} bytes).",
                }
            ],
        }

    if mode != "creality_webrtc":
        raise CameraError("This camera source type does not have a diagnostic check.")

    base = endpoint(connection)
    control_port = base.port or 9999
    control_address = resolve_address(base.hostname, control_port)
    control_socket = None
    try:
        control_socket = socket.create_connection((control_address, control_port), timeout=2)
    except (OSError, TimeoutError) as exc:
        raise CameraError(f"Creality control channel on port {control_port} could not be reached.") from exc
    finally:
        if control_socket:
            control_socket.close()

    parsed = urlsplit(source["url"])
    camera_port = parsed.port or (443 if parsed.scheme == "https" else 80)
    camera_address = resolve_address(parsed.hostname, camera_port)
    camera_socket = None
    try:
        camera_socket = socket.create_connection((camera_address, camera_port), timeout=2)
    except (OSError, TimeoutError) as exc:
        raise CameraError(f"Creality camera service on port {camera_port} could not be reached.") from exc
    finally:
        if camera_socket:
            camera_socket.close()

    token, protected = creality_session(connection)
    session_detail = (
        "Protected video session token received."
        if protected and token
        else "Camera session is reachable and does not require a protected video token."
    )
    return {
        "ok": True,
        "mode": mode,
        "checks": [
            {"id": "control", "ok": True, "detail": f"Creality control channel is reachable on port {control_port}."},
            {"id": "camera", "ok": True, "detail": f"Creality camera service is reachable on port {camera_port}."},
            {"id": "session", "ok": True, "detail": session_detail},
        ],
    }


def fix_creality_answer_sdp(value):
    """Repair the K2/K2 Pro/K2 Plus SDP quirk handled by go2rtc #format=creality.

    Creality answers can list a bogus first video payload while RTP arrives on
    the following codec. Browsers accept the SDP but never surface usable video.
    """
    if not isinstance(value, str) or not value.startswith("v=0"):
        raise CameraError("Printer did not return a valid WebRTC answer.")

    lines = value.replace("\r\n", "\n").split("\n")
    video_index = next((i for i, line in enumerate(lines) if line.startswith("m=video ")), None)
    if video_index is None:
        raise CameraError("Printer WebRTC answer did not include a video stream.")

    parts = lines[video_index].split()
    if len(parts) < 5:
        return value

    skipped = parts[3]
    parts = parts[:3] + parts[4:]
    lines[video_index] = " ".join(parts)

    end = next((i for i in range(video_index + 1, len(lines)) if lines[i].startswith("m=")), len(lines))
    repaired = lines[:video_index + 1]
    for line in lines[video_index + 1:end]:
        if line.startswith(f"a=rtpmap:{skipped} ") or line.startswith(f"a=fmtp:{skipped} "):
            continue
        if line.startswith("a=fmtp:") and "x-google" in line:
            continue
        repaired.append(line)
    repaired.extend(lines[end:])

    result = "\r\n".join(line for line in repaired if line != "") + "\r\n"
    return result


def negotiate(connection, source, offer):
    if source["mode"] != "creality_webrtc":
        raise CameraError("This camera does not use Creality WebRTC.")
    if not isinstance(offer, str) or len(offer) > 65536 or not offer.startswith("v=0") or "m=video " not in offer or "m=application " in offer or "m=audio " in offer:
        raise CameraError("Provide a bounded video-only WebRTC offer.")
    token, protected = creality_session(connection)
    url = source["url"]
    body = {"type": "offer", "sdp": offer}
    if protected:
        # Keep signaling on the exact validated camera origin (normally :8000).
        # Older code rebuilt the URL from hostname only and silently dropped the port.
        body["token"] = token
    encoded = base64.b64encode(json.dumps(body).encode("utf-8"))
    pool, response = upstream(connection, url, method="POST", body=encoded, content_type="plain/text")
    try:
        answer = json.loads(base64.b64decode(read_bounded(response, MAX_JSON).strip(), validate=True))
        if not isinstance(answer, dict) or answer.get("type") != "answer" or not isinstance(answer.get("sdp"), str) or len(answer["sdp"]) > 65536 or not answer["sdp"].startswith("v=0"):
            raise CameraError("Printer did not return a valid WebRTC answer.")
        return {"type": "answer", "sdp": fix_creality_answer_sdp(answer["sdp"])}
    except CameraError:
        raise
    except (ValueError, urllib3.exceptions.HTTPError, OSError) as exc:
        raise CameraError("Printer returned an unsupported camera response. Check its firmware and camera availability.") from exc
    finally:
        response.close()
        pool.close()
