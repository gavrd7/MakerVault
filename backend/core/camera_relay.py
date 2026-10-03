from __future__ import annotations

import hashlib
import hmac
import ipaddress
import os
import socket
from urllib.parse import quote, urlsplit

import requests
from django.conf import settings


GO2RTC_API = os.environ.get("MAKERVAULT_CAMERA_RELAY_API", "http://127.0.0.1:1984").rstrip("/")
BRIDGE_PORT = int(os.environ.get("MAKERVAULT_CAMERA_RELAY_BRIDGE_PORT", "1985"))
MEDIA_PORT = int(os.environ.get("MAKERVAULT_CAMERA_RELAY_PORT", "8555"))

_SESSION = requests.Session()
_SESSION.trust_env = False


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


def _request_candidate_host(request) -> str:
    override = os.environ.get("MAKERVAULT_CAMERA_RELAY_CANDIDATE", "").strip()
    if override:
        return override.strip("[]")

    raw_host = request.get_host()
    hostname = urlsplit(f"//{raw_host}").hostname or ""
    if not hostname:
        raise CameraRelayError("MakerVault could not determine the camera relay address.")

    try:
        ipaddress.ip_address(hostname)
        return hostname
    except ValueError:
        pass

    try:
        answers = socket.getaddrinfo(hostname, MEDIA_PORT, type=socket.SOCK_STREAM)
    except OSError as exc:
        raise CameraRelayError(
            "Set MAKERVAULT_CAMERA_RELAY_CANDIDATE to the LAN/VPN address clients use for MakerVault."
        ) from exc

    for answer in answers:
        candidate = answer[4][0]
        try:
            ip = ipaddress.ip_address(candidate)
        except ValueError:
            continue
        if not ip.is_loopback and not ip.is_unspecified:
            return candidate

    raise CameraRelayError(
        "Set MAKERVAULT_CAMERA_RELAY_CANDIDATE to the LAN/VPN address clients use for MakerVault."
    )


def rewrite_answer_candidates(sdp: str, request) -> str:
    host = _request_candidate_host(request)
    port = str(MEDIA_PORT)
    rewritten = []
    for line in sdp.replace("\r\n", "\n").split("\n"):
        if line.startswith("a=candidate:"):
            fields = line.split(" ")
            if len(fields) >= 6 and fields[4] in {"127.0.0.1", "::1"}:
                fields[4] = host
                fields[5] = port
                line = " ".join(fields)
        rewritten.append(line)
    return "\r\n".join(rewritten).rstrip("\r\n") + "\r\n"


def relay_offer(request, connection_id, camera_id: str, offer: str) -> dict:
    if (
        not isinstance(offer, str)
        or len(offer) > 65536
        or not offer.startswith("v=0")
        or "m=video " not in offer
        or "m=application " in offer
    ):
        raise CameraRelayError("Provide a bounded video WebRTC offer.")

    name = ensure_stream(connection_id, camera_id)
    try:
        response = _SESSION.post(
            f"{GO2RTC_API}/api/webrtc",
            params={"src": name},
            json={"type": "offer", "sdp": offer},
            timeout=(2, 20),
            allow_redirects=False,
        )
    except requests.RequestException as exc:
        raise CameraRelayError("The camera compatibility relay could not negotiate video.") from exc

    if response.status_code < 200 or response.status_code >= 300:
        raise CameraRelayError("The camera compatibility relay rejected the video session.")

    try:
        answer = response.json()
    except ValueError as exc:
        raise CameraRelayError("The camera compatibility relay returned an invalid response.") from exc

    if (
        not isinstance(answer, dict)
        or answer.get("type") != "answer"
        or not isinstance(answer.get("sdp"), str)
        or not answer["sdp"].startswith("v=0")
        or len(answer["sdp"]) > 65536
    ):
        raise CameraRelayError("The camera compatibility relay returned an invalid WebRTC answer.")

    return {"type": "answer", "sdp": rewrite_answer_candidates(answer["sdp"], request)}
