from django.test import SimpleTestCase

from core.management.commands.diagnose_camera_relay import safe_codec_info, safe_stream_state


class RelayTrackInspectionTests(SimpleTestCase):
    def test_whitelists_codec_metadata_and_never_exposes_credentials(self):
        payload = {
            "camera": {
                "url": "webrtc:http://printer.lan:8000/?sig=secret",
                "producers": [{
                    "url": "http://user:password@printer.lan",
                    "remote_addr": "192.168.1.50",
                    "medias": [{
                        "direction": "recvonly",
                        "kind": "video",
                        "codecs": [
                            {"codec_name": "H264", "fmtp_line": "token=secret"},
                            {"codec_name": "unknown", "username": "password"},
                        ],
                    }],
                }],
                "consumers": [{"medias": [{"kind": "video", "codecs": [{"codec_name": "H264"}]}]}],
            }
        }
        result = safe_stream_state(payload, "camera")
        self.assertEqual(result["producer_count"], 1)
        self.assertEqual(result["consumer_count"], 1)
        self.assertEqual(result["producers"][0]["tracks"][0]["codecs"], ["h264", "other"])
        self.assertEqual(result["consumers"][0]["tracks"][0]["codecs"], ["h264"])
        result_text = str(result)
        for secret in ("secret", "password", "192.168.1.50", "printer.lan", "fmtp_line"):
            self.assertNotIn(secret, result_text)

    def test_unknown_or_absent_streams_do_not_leak_raw_payload(self):
        self.assertEqual(safe_stream_state({"some_other_stream": {"url": "secret"}}, "camera")["status"], "stream not registered in go2rtc")
        self.assertEqual(safe_stream_state("not json", "camera")["status"], "unexpected go2rtc response format")
        self.assertEqual(safe_codec_info({"codec_name": "H265", "fmtp_line": "token=secret"}), "h265")
