"""Inspect go2rtc HLS metadata without exposing source URLs or media payloads.

Run inside an existing staging app container while viewing the camera.
This creates a temporary HLS consumer. It makes no configuration changes.
"""
import re
from time import sleep, monotonic

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

def transport_packet_summary(payload):
    """Report packet types only; never expose video bytes or packet contents."""
    if not payload or len(payload) % 188:
        return {"valid_ts": False, "packets": 0}
    tables = 0
    other_packets = 0
    payload_packets = 0
    pes_starts = 0
    for offset in range(0, len(payload), 188):
        packet = payload[offset:offset + 188]
        if packet[0] != 0x47:
            return {"valid_ts": False, "packets": len(payload) // 188}
        pid = ((packet[1] & 0x1F) << 8) | packet[2]
        if pid in {0, 0x1FFF} or pid < 0x20:
            tables += 1
        else:
            other_packets += 1
        afc = (packet[3] >> 4) & 0x03
        if afc in {1, 3}:
            position = 4
            if afc == 3:
                position += 1 + packet[4]
            if position < 188:
                payload_packets += 1
                if packet[1] & 0x40 and packet[position:position + 3] == b"\x00\x00\x01":
                    pes_starts += 1
    return {
        "valid_ts": True,
        "packets": len(payload) // 188,
        "table_or_reserved_packets": tables,
        "other_pid_packets": other_packets,
        "packets_with_payload": payload_packets,
        "pes_starts": pes_starts,
    }


class Command(BaseCommand):
    help = "Check safe HLS playlist and MP4 initialization dimensions for Creality cameras."

    def add_arguments(self, parser):
        parser.add_argument("--watch-ts", action="store_true", help="Request bounded MPEG-TS segments and measure whether the live playlist advances.")

    def probe_ts_segments(self, session):
        """Consume bounded TS segments; playlist polling alone cannot advance go2rtc."""
        for sample in range(3):
            started = monotonic()
            payload, _ = hls_resource(session, "playlist.m3u8")
            state = ts_playlist_progress(payload.decode("utf-8"))
            if not state.get("valid") or not state["segment_numbers"]:
                self.stdout.write(f"  Sample {sample + 1}: no valid TS segment references")
                return
            number = state["segment_numbers"][0]
            if number is None:
                self.stdout.write(f"  Sample {sample + 1}: missing segment sequence")
                return
            try:
                segment, mime = hls_resource(session, "segment.ts", sequence=str(number))
                elapsed = round(monotonic() - started, 2)
                packet_info = transport_packet_summary(segment)
                valid_ts = packet_info["valid_ts"]
                self.stdout.write(
                    f"  Sample {sample + 1}: playlist_sequence={state['media_sequence']}, "
                    f"requested_segment={number}, bytes={len(segment)}, "
                    f"elapsed_seconds={elapsed}, ts_sync={valid_ts}, "
                    f"mime_ok={mime == 'video/mp2t'}, packets={packet_info['packets']}, "
                    f"other_pid_packets={packet_info.get('other_pid_packets', 0)}, "
                    f"pes_starts={packet_info.get('pes_starts', 0)}"
                )
                if not valid_ts:
                    self.stdout.write("  MPEG-TS segment is empty or does not start with a sync byte.")
                    return
            except CameraRelayError:
                self.stdout.write(f"  Sample {sample + 1}: segment request failed after {round(monotonic() - started, 2)}s")
                return
        payload, _ = hls_resource(session, "playlist.m3u8")
        state = ts_playlist_progress(payload.decode("utf-8"))
        self.stdout.write(
            f"  After segment consumption: playlist_sequence={state.get('media_sequence')}, "
            f"segment_numbers={state.get('segment_numbers')}"
        )

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
                        self.probe_ts_segments(session)
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
