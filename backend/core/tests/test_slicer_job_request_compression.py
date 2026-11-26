"""Large paint regions must transit losslessly without weakening admission checks."""
import gzip
import json
from unittest.mock import patch

from django.test import RequestFactory, SimpleTestCase

from core.slicer_api import (
    _slicer_request_json, MAX_SLICER_JSON_BYTES, MAX_SLICER_REQUEST_BYTES,
)


class LargeSlicerJobPayloadTests(SimpleTestCase):
    def setUp(self):
        self.factory = RequestFactory()

    def request(self, payload, *, encoding=None):
        kwargs = {"content_type": "application/json"}
        if encoding:
            kwargs["HTTP_CONTENT_ENCODING"] = encoding
        return self.factory.post("/api/printing/slicer/jobs/", payload, **kwargs)

    def test_gzip_round_trips_precise_polygon_coordinates(self):
        polygon = [
            [0.123456789012345, 1.23456789012345, 2.3456789012345],
            [4.56789012345678, 5.67890123456789, 6.7890123456789],
            [7.89012345678901, 8.90123456789012, 9.0123456789012],
        ]
        # Representative paint payload that exceeds the uncompressed 8 MiB
        # transfer cap but compresses well below it.
        value = {
            "settings": {"plate_objects": [{"support_paint": {
                "version": 2, "signature": "200000:ffffabcd",
                "regions": [{"slot": 0, "patches": [
                    {"face": index, "polygon": polygon} for index in range(50000)
                ]}],
            }}]},
        }
        raw = json.dumps(value).encode()
        self.assertGreater(len(raw), MAX_SLICER_REQUEST_BYTES)
        compressed = gzip.compress(raw)
        self.assertLess(len(compressed), MAX_SLICER_REQUEST_BYTES)
        decoded = _slicer_request_json(self.request(compressed, encoding="gzip"))
        self.assertEqual(decoded, value)
        self.assertEqual(decoded["settings"]["plate_objects"][0]["support_paint"]["regions"][0]
                         ["patches"][0]["polygon"], polygon)

    def test_draft_accepts_large_valid_json_past_obsolete_128k_limit(self):
        from unittest.mock import patch
        from core.slicer_api import _draft
        # Structural validation should run on expanded JSON, rather than
        # rejecting it unconditionally at 128 KiB before checking the engine.
        large = {"engine": "orcaslicer",
                 "settings": {"support_paint": "x" * (256 * 1024)}}
        with patch("core.slicer_api.get_engine",
                   side_effect=ValueError("Reached native engine validation")):
            with self.assertRaisesRegex(ValueError, "Reached native engine validation"):
                _draft(None, large)

    def test_internal_draft_still_rejects_unbounded_expanded_json(self):
        from core.slicer_api import _draft
        # The request limit is live-memory based; force a known headroom so
        # this checks the size gate rather than the following engine gate.
        with patch("core.slicer_api.slicer_configuration_limits",
                   return_value=(MAX_SLICER_REQUEST_BYTES, MAX_SLICER_JSON_BYTES)):
            with self.assertRaisesRegex(ValueError, "expanded request memory"):
                _draft(None, {"settings": {"support_paint":
                                           "x" * (MAX_SLICER_JSON_BYTES + 1)}})

    def test_normal_json_remains_accepted(self):
        data = {"engine": "orcaslicer", "settings": {"plate_objects": []}}
        decoded = _slicer_request_json(self.request(json.dumps(data).encode()))
        self.assertEqual(decoded, data)

    def test_invalid_or_ambiguous_encoding_rejected(self):
        body = gzip.compress(b'{"ok": true}')
        for encoded, header in (
            (body[:-4], "gzip"),
            (body + b"EXTRA", "gzip"),
            (body, "deflate"),
            (b"not gzip", "gzip"),
        ):
            with self.subTest(header=header, count=len(encoded)):
                with self.assertRaises(ValueError):
                    _slicer_request_json(self.request(encoded, encoding=header))

    def test_expansion_limit_is_enforced_before_parsing(self):
        raw = b"x" * (MAX_SLICER_JSON_BYTES + 1)
        with patch("core.slicer_api.slicer_configuration_limits",
                   return_value=(MAX_SLICER_REQUEST_BYTES, MAX_SLICER_JSON_BYTES)):
            with self.assertRaisesRegex(ValueError, "expanded safety limit"):
                _slicer_request_json(self.request(gzip.compress(raw), encoding="gzip"))
