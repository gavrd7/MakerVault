from django.test import SimpleTestCase

from core.management.commands.diagnose_camera_hls import (
    init_mp4_dimensions,
    playlist_summary,
    session_from_master,
    ts_playlist_progress,
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
