from unittest.mock import patch

from django.test import SimpleTestCase

from core.management.commands.diagnose_camera_hls import (
    init_mp4_dimensions,
    playlist_summary,
    session_from_master,
    ts_playlist_progress,
    transport_packet_summary,
    Command,
)


class CameraHlsMetadataTests(SimpleTestCase):
    def test_playlist_reports_only_codec_and_resolution_not_signed_urls(self):
        playlist = (
            '#EXTM3U\n#EXT-X-STREAM-INF:BANDWIDTH=1000000,'
            'CODECS="avc1.640029,mp4a.40.2",RESOLUTION=1280x960\n'
            'hls/playlist.m3u8?id=secret-session\n'
        )
        result = playlist_summary(playlist)
        self.assertEqual(result["advertised_resolutions"], ["1280x960"])
        self.assertEqual(result["codecs"], ["avc1.640029", "mp4a.40.2"])
        self.assertNotIn("secret-session", str(result))
        self.assertEqual(session_from_master(playlist), "secret-session")

    def test_mp4_avc1_sample_entry_resolution(self):
        # Visual sample entry size 36: type at offset 4, width/height at 32/34.
        box = bytearray(36)
        box[0:4] = (36).to_bytes(4, "big")
        box[4:8] = b"avc1"
        box[32:34] = (1280).to_bytes(2, "big")
        box[34:36] = (960).to_bytes(2, "big")
        self.assertEqual(init_mp4_dimensions(b"other" + bytes(box)), ["1280x960"])
        self.assertEqual(init_mp4_dimensions(b"no sample entry"), [])

    def test_missing_metadata_does_not_invent_video_resolution(self):
        self.assertEqual(playlist_summary("#EXTM3U\n#EXTINF:2,\nsegment.m4s?id=x\n")["advertised_resolutions"], [])
        self.assertIsNone(session_from_master("#EXTM3U\n"))

    def test_native_ts_playlist_sequence_progress_and_redaction(self):
        first = (
            "#EXTM3U\n#EXT-X-TARGETDURATION:2\n#EXT-X-MEDIA-SEQUENCE:7\n"
            "#EXTINF:2,\nsegment.ts?id=private-session&n=7\n"
            "#EXTINF:2,\nsegment.ts?id=private-session&n=8\n"
        )
        second = first.replace("SEQUENCE:7", "SEQUENCE:8").replace("&n=7", "&n=9")
        a = ts_playlist_progress(first)
        b = ts_playlist_progress(second)
        self.assertEqual(a["media_sequence"], 7)
        self.assertEqual(a["segment_numbers"], [7, 8])
        self.assertEqual(b["media_sequence"], 8)
        self.assertNotEqual(a["segment_numbers"], b["segment_numbers"])
        self.assertEqual(a["target_duration"], 2)
        self.assertNotIn("private-session", str(a))

    @patch("core.management.commands.diagnose_camera_hls.hls_resource")
    def test_live_ts_diagnostic_consumes_segments_not_just_playlists(self, resource):
        sequences = iter([0, 1, 2, 3])
        def reply(_session, kind, **kwargs):
            if kind == "playlist.m3u8":
                number = next(sequences)
                body = (
                    f"#EXTM3U\n#EXT-X-MEDIA-SEQUENCE:{number}\n"
                    f"#EXTINF:0.5,\nsegment.ts?id=private&n={number}\n"
                ).encode()
                return body, "application/vnd.apple.mpegurl"
            self.assertEqual(kind, "segment.ts")
            self.assertIn(kwargs.get("sequence"), {"0", "1", "2"})
            return b"\x47" + b"packet", "video/mp2t"
        resource.side_effect = reply
        lines = []
        cmd = Command()
        cmd.stdout.write = lines.append
        cmd.probe_ts_segments("private")
        self.assertEqual(sum("requested_segment=" in line for line in lines), 3)
        self.assertTrue(any("playlist_sequence=3" in line for line in lines))
        self.assertNotIn("private", str(lines))

    def test_transport_packet_probe_distinguishes_tables_from_video_payload(self):
        def packet(pid, payload_start=False, content=b""):
            data = bytearray(188)
            data[0] = 0x47
            data[1] = ((pid >> 8) & 0x1f) | (0x40 if payload_start else 0)
            data[2] = pid & 0xff
            data[3] = 0x10
            data[4:4 + len(content)] = content
            return bytes(data)
        tables = packet(0) + packet(0x100)
        result = transport_packet_summary(tables)
        self.assertTrue(result["valid_ts"])
        self.assertEqual(result["packets"], 2)
        self.assertEqual(result["pes_starts"], 0)
        self.assertEqual(result["other_pid_packets"], 1)
        video = packet(0x101, True, b"\x00\x00\x01\xe0")
        result = transport_packet_summary(tables + video)
        self.assertEqual(result["pes_starts"], 1)
        self.assertEqual(result["other_pid_packets"], 2)
