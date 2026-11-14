"""Read-only, credential-safe view of go2rtc Creality camera track state.

Run while viewing the printer dashboard:
    docker exec makervault python manage.py diagnose_camera_relay

Only whitelisted transport metadata is printed. No source addresses, WebRTC SDP,
camera tokens, relay signatures, or configured printer URLs are displayed.
"""
import json

import requests
from django.core.management.base import BaseCommand

from core.camera_relay import GO2RTC_API, stream_name
from core.models import PrinterConnection
from core.printer_cameras import sources


def safe_codec_info(codec):
    if isinstance(codec, str):
        # Codec names only; do not print arbitrary upstream parameters.
        name = codec.split("/", 1)[0].strip().lower()
        return name if name in {"h264", "h265", "hevc", "av1", "vp8", "vp9", "aac", "opus", "pcm", "pcma", "pcmu"} else "other"
    if not isinstance(codec, dict):
        return "unknown"
    name = str(codec.get("codec_name") or codec.get("name") or "").lower()
    return name if name in {"h264", "h265", "hevc", "av1", "vp8", "vp9", "aac", "opus", "pcm", "pcma", "pcmu"} else "other"


def safe_tracks(items):
    if not isinstance(items, list):
        return []
    result = []
    for item in items[:12]:
        if not isinstance(item, dict):
            continue
        medias = item.get("medias") or []
        tracks = []
        if isinstance(medias, list):
            for media in medias[:12]:
                if not isinstance(media, dict):
                    continue
                codecs = media.get("codecs") or []
                tracks.append({
                    "direction": str(media.get("direction") or "") if media.get("direction") in {"sendonly", "recvonly", "sendrecv", "inactive"} else "unknown",
                    "kind": str(media.get("kind") or "") if media.get("kind") in {"video", "audio"} else "unknown",
                    "codecs": [safe_codec_info(codec) for codec in codecs[:12]] if isinstance(codecs, list) else [],
                })
        result.append({"tracks": tracks})
    return result


def safe_stream_state(data, name):
    # go2rtc may return a keyed stream collection or an individual stream.
    if isinstance(data, dict) and isinstance(data.get(name), dict):
        data = data[name]
    if not isinstance(data, dict):
        return {"status": "unexpected go2rtc response format"}
    return {
        "producers": safe_tracks(data.get("producers")),
        "consumers": safe_tracks(data.get("consumers")),
        "producer_count": len(data.get("producers") or []) if isinstance(data.get("producers"), list) else 0,
        "consumer_count": len(data.get("consumers") or []) if isinstance(data.get("consumers"), list) else 0,
    }


class Command(BaseCommand):
    help = "Inspect active Creality relay tracks without exposing URLs, tokens or SDP."

    def handle(self, *args, **options):
        session = requests.Session()
        session.trust_env = False
        camera_index = 0
        for connection in PrinterConnection.objects.filter(adapter="creality_local", enabled=True).order_by("pk"):
            for camera in sources(connection):
                if camera.get("mode") != "creality_webrtc":
                    continue
                camera_index += 1
                name = stream_name(connection.pk, camera["id"])
                try:
                    response = session.get(
                        f"{GO2RTC_API}/api/streams",
                        params={"src": name},
                        timeout=(2, 5),
                        allow_redirects=False,
                    )
                    if response.status_code != 200:
                        result = {"status": f"go2rtc returned HTTP {response.status_code}"}
                    elif len(response.content) > 262144:
                        result = {"status": "go2rtc response too large"}
                    else:
                        result = safe_stream_state(response.json(), name)
                except (requests.RequestException, ValueError, TypeError):
                    result = {"status": "go2rtc stream inspection unavailable"}
                self.stdout.write(f"Camera {camera_index}: {json.dumps(result, sort_keys=True)}")
        if not camera_index:
            self.stdout.write("No enabled Creality WebRTC cameras configured.")
        else:
            self.stdout.write("Read-only diagnostic complete. Play the cameras during inspection to see active tracks.")
