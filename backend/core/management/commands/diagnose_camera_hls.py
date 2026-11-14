"""Inspect go2rtc HLS metadata without exposing source URLs or media payloads.

Run inside an existing staging app container while viewing the camera.
This creates a temporary HLS consumer. It makes no configuration changes.
"""
import re
from time import sleep

from django.core.management.base import BaseCommand

from core.camera_relay import CameraRelayError, hls_master, hls_resource
from core.models import PrinterConnection
from core.printer_cameras import sources


def playlist_summary(text):
    if not isinstance(text, str) or not text.startswith("#EXTM3U"):
        return {"valid": False}
    codecs = []
    for value in re.findall(r'CODECS="([^"]{1,120})"', text):
        for codec in value.split(","):
            name = codec.strip().lower()
            if re.fullmatch(r"(?:avc1|avc3|hvc1|hev1|mp4a)\.[a-z0-9.]+", name):
                codecs.append(name)
    dimensions = []
    for width, height in re.findall(r"RESOLUTION=(\d{1,5})x(\d{1,5})", text):
        if 0 < int(width) <= 16384 and 0 < int(height) <= 16384:
            dimensions.append(f"{width}x{height}")
    return {
        "valid": True,
        "codecs": codecs[:8],
        "advertised_resolutions": dimensions[:8],
        "init_mp4_referenced": '#EXT-X-MAP:' in text,
        "segment_m4s_referenced": "segment.m4s?" in text,
        "segment_ts_referenced": "segment.ts?" in text,
    }


def init_mp4_dimensions(data):
    """Read width/height in an MP4 avc1/avc3 visual sample entry."""
    if not isinstance(data, bytes):
        return []
    result = []
    offset = 0
    # A bounded read-only scan; treat every hit as provisional visual sample entry.
    while offset < len(data):
        position = data.find(b"avc1", offset)
        position2 = data.find(b"avc3", offset)
        hits = [pos for pos in (position, position2) if pos >= 0]
        if not hits:
            break
        pos = min(hits)
        # 'avc1' is the box type at box_start+4; width at box_start+32.
        if pos >= 4 and pos + 32 <= len(data):
            start = pos - 4
            size = int.from_bytes(data[start:pos], "big")
            if 36 <= size <= len(data) - start:
                width = int.from_bytes(data[start + 32:start + 34], "big")
                height = int.from_bytes(data[start + 34:start + 36], "big")
                if 0 < width <= 16384 and 0 < height <= 16384:
                    result.append(f"{width}x{height}")
        offset = pos + 4
    return result[:8]


def session_from_master(master):
    for line in master.splitlines():
        if line.startswith("#"):
            continue
        match = re.search(r"(?:\?|&)id=([A-Za-z0-9_-]{1,128})(?:&|$)", line)
        if match:
            return match.group(1)
    return None



def ts_playlist_progress(text):
    """Return safe live-playlist progression metadata without session URLs."""
    if not isinstance(text, str) or not text.startswith("#EXTM3U"):
        return {"valid": False}
    sequence = None
    target = None
    segments = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if line.startswith("#EXT-X-MEDIA-SEQUENCE:"):
            value = line.partition(":")[2]
            sequence = int(value) if value.isascii() and value.isdecimal() and len(value) <= 16 else None
        elif line.startswith("#EXT-X-TARGETDURATION:"):
            value = line.partition(":")[2]
            target = int(value) if value.isascii() and value.isdecimal() and len(value) <= 6 else None
        elif line and not line.startswith("#"):
            resource, _, query = line.partition("?")
            if resource.rsplit("/", 1)[-1] not in {"segment.ts", "segment.m4s"}:
                continue
            number = None
            for part in query.split("&"):
                if part.startswith("n="):
                    value = part[2:]
                    number = int(value) if value.isascii() and value.isdecimal() and len(value) <= 16 else None
                    break
            segments.append(number)
    return {
        "valid": True,
        "media_sequence": sequence,
        "target_duration": target,
        "segment_count": len(segments),
        "segment_numbers": segments[-8:],
        "has_endlist": "#EXT-X-ENDLIST" in text,
    }

class Command(BaseCommand):
    help = "Check safe HLS playlist and MP4 initialization dimensions for Creality cameras."

    def add_arguments(self, parser):
        parser.add_argument("--watch-ts", action="store_true", help="Compare three native MPEG-TS HLS playlist snapshots, four seconds apart.")

    def handle(self, *args, **kwargs):
        count = 0
        for connection in PrinterConnection.objects.filter(adapter="creality_local", enabled=True).order_by("pk"):
            for camera in sources(connection):
                if camera.get("mode") != "creality_webrtc":
                    continue
                count += 1
                self.stdout.write(f"Camera {count}:")
                try:
                    if kwargs.get("watch_ts"):
                        master = hls_master(connection.pk, camera["id"], mpeg_ts=True)
                        session = session_from_master(master)
                        if not session:
                            self.stdout.write("  No HLS session in TS master.")
                            continue
                        previous = None
                        for index in range(3):
                            if index:
                                sleep(4)
                            body, _ = hls_resource(session, "playlist.m3u8")
                            progress = ts_playlist_progress(body.decode("utf-8"))
                            progress["changed"] = None if previous is None else (
                                progress["media_sequence"] != previous["media_sequence"]
                                or progress["segment_numbers"] != previous["segment_numbers"]
                            )
                            self.stdout.write(f"  Sample {index + 1}: {progress}")
                            previous = progress
                        continue
                    master = hls_master(connection.pk, camera["id"])
                    self.stdout.write(f"  master: {playlist_summary(master)}")
                    session = session_from_master(master)
                    if not session:
                        self.stdout.write("  no HLS session in master")
                        continue
                    # go2rtc can need a moment to initialise the HLS session.
                    media = ""
                    for _ in range(3):
                        try:
                            body, _ = hls_resource(session, "playlist.m3u8")
                            media = body.decode("utf-8")
                            break
                        except (CameraRelayError, UnicodeError):
                            sleep(0.5)
                    if media:
                        self.stdout.write(f"  media: {playlist_summary(media)}")
                        if '#EXT-X-MAP:' in media:
                            init, _ = hls_resource(session, "init.mp4")
                            self.stdout.write(f"  MP4 AVC sample entry dimensions: {init_mp4_dimensions(init)}")
                    else:
                        self.stdout.write("  media playlist unavailable")
                except (CameraRelayError, ValueError, TypeError, UnicodeError, OSError):
                    self.stdout.write("  HLS inspection unavailable (see application logs)")
        if not count:
            self.stdout.write("No enabled Creality WebRTC cameras.")
