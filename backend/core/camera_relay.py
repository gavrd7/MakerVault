from __future__ import annotations

import hashlib
import hmac
import json
import os
from urllib.parse import quote

import requests
from django.conf import settings


GO2RTC_API = os.environ.get("MAKERVAULT_CAMERA_RELAY_API", "http://127.0.0.1:1984").rstrip("/")
BRIDGE_PORT = int(os.environ.get("MAKERVAULT_CAMERA_RELAY_BRIDGE_PORT", "1985"))

_SESSION = requests.Session()
_SESSION.trust_env = False

_PLAYLIST_MAX_BYTES = 512 * 1024
_SEGMENT_MAX_BYTES = 16 * 1024 * 1024
_HLS_RESOURCES = {
    "playlist.m3u8": _PLAYLIST_MAX_BYTES,
    "init.mp4": _SEGMENT_MAX_BYTES,
    "segment.m4s": _SEGMENT_MAX_BYTES,
    "segment.ts": _SEGMENT_MAX_BYTES,
}


class CameraRelayError(ValueError):
    """Raised when MakerVault's local K2 compatibility relay cannot be used."""


def stream_name(connection_id, camera_id: str) -> str:
    digest = hashlib.sha256(f"{connection_id}:{camera_id}".encode("utf-8")).hexdigest()[:24]
    return f"makervault_{digest}"


def bridge_signature(connection_id, camera_id: str) -> str:
    key = str(settings.SECRET_KEY).encode("utf-8")
    payload = f"camera-relay:{connection_id}:{camera_id}".encode("utf-8")
    return hmac.new(key, payload, hashlib.sha256).hexdigest()


def valid_bridge_signature(connection_id, camera_id: str, candidate: str) -> bool:
    expected = bridge_signature(connection_id, camera_id)
    return bool(candidate) and hmac.compare_digest(expected, str(candidate))


def bridge_source(connection_id, camera_id: str) -> str:
    token = bridge_signature(connection_id, camera_id)
    safe_camera = quote(str(camera_id), safe="")
    return (
        f"webrtc:http://127.0.0.1:{BRIDGE_PORT}/creality/"
        f"{connection_id}/{safe_camera}?sig={token}#format=creality"
    )


def ensure_stream(connection_id, camera_id: str) -> str:
    name = stream_name(connection_id, camera_id)
    try:
        response = _SESSION.patch(
            f"{GO2RTC_API}/api/streams",
            params={"name": name, "src": bridge_source(connection_id, camera_id)},
            timeout=(1.5, 3),
            allow_redirects=False,
        )
    except requests.RequestException as exc:
        raise CameraRelayError("The camera compatibility relay is unavailable.") from exc
    if response.status_code < 200 or response.status_code >= 300:
        raise CameraRelayError("The camera compatibility relay could not prepare this stream.")
    return name


def _bounded_get(path: str, *, params=None, max_bytes: int, timeout=(2, 20)):
    try:
        response = _SESSION.get(
            f"{GO2RTC_API}{path}",
            params=params or {},
            timeout=timeout,
            allow_redirects=False,
            stream=True,
        )
    except requests.RequestException as exc:
        raise CameraRelayError("The camera compatibility relay is unavailable.") from exc

    if response.status_code < 200 or response.status_code >= 300:
        status = response.status_code
        response.close()
        raise CameraRelayError(f"The camera compatibility relay returned HTTP {status}.")

    declared = response.headers.get("Content-Length")
    if declared and declared.isdigit() and int(declared) > max_bytes:
        response.close()
        raise CameraRelayError("The camera relay response exceeded MakerVault's safety limit.")

    chunks = []
    total = 0
    try:
        for chunk in response.iter_content(chunk_size=64 * 1024):
            if not chunk:
                continue
            total += len(chunk)
            if total > max_bytes:
                raise CameraRelayError("The camera relay response exceeded MakerVault's safety limit.")
            chunks.append(chunk)
        content_type = response.headers.get("Content-Type", "application/octet-stream").split(";", 1)[0].strip()
        return b"".join(chunks), content_type
    finally:
        response.close()


def hls_master(connection_id, camera_id: str) -> str:
    """Create/refresh the protected K2 source and return go2rtc's HLS/fMP4 master playlist."""
    name = ensure_stream(connection_id, camera_id)
    data, _content_type = _bounded_get(
        "/api/stream.m3u8",
        params={"src": name, "mp4": ""},
        max_bytes=_PLAYLIST_MAX_BYTES,
    )
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise CameraRelayError("The camera relay returned an invalid HLS playlist.") from exc
    if not text.startswith("#EXTM3U"):
        raise CameraRelayError("The camera relay returned an invalid HLS playlist.")
    return text


def hls_resource(session_id: str, resource: str):
    """Fetch a bounded HLS resource from the loopback-only go2rtc API."""
    if resource not in _HLS_RESOURCES:
        raise CameraRelayError("Unsupported camera relay resource.")
    if not session_id or len(session_id) > 128 or not all(ch.isalnum() or ch in "_-" for ch in session_id):
        raise CameraRelayError("Invalid camera relay session.")
    return _bounded_get(
        f"/api/hls/{resource}",
        params={"id": session_id},
        max_bytes=_HLS_RESOURCES[resource],
    )
