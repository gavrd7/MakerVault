from django.test import SimpleTestCase

from core.slicer_colour_painting import validate_colour_paint


class ColourPaintDraftTests(SimpleTestCase):
    def setUp(self):
        self.paint = {
            "version": 1, "signature": "12:abcdef01",
            "palette": [
                {"color": "#58B5E4", "label": "Preview colour 1"},
                {"color": "#FF0000", "label": "Loaded slot 2",
                 "printer_id": "12345678-1234-1234-1234-123456789abc",
                 "slot_id": "CFS-B-2", "slot_index": 1},
            ],
            "faces": {"0": 1, "11": 0},
        }

    def test_round_trip_preserves_sparse_faces_and_advisory_palette(self):
        saved = validate_colour_paint(self.paint)
        self.assertEqual(saved["faces"], {"0": 1, "11": 0})
        self.assertEqual(saved["palette"][0]["color"], "#58b5e4")
        self.assertEqual(saved["palette"][1]["slot_id"], "CFS-B-2")

    def test_rejects_stale_or_invalid_face_indices_and_slots(self):
        for faces in ({"12": 0}, {"-1": 0}, {"01": 0}, {"0": 2}, {"0": True}):
            with self.subTest(faces=faces), self.assertRaises(ValueError):
                validate_colour_paint({**self.paint, "faces": faces})

    def test_rejects_invalid_palette_or_schema(self):
        variants = (
            {**self.paint, "version": 2},
            {**self.paint, "signature": "500001:abc"},
            {**self.paint, "palette": []},
            {**self.paint, "palette": [{"color": "red", "label": "Red"}]},
            {**self.paint, "palette": [{"color": "#ff0000", "label": "bad\\x00text"}]},
            {**self.paint, "palette": [{"color": "#ff0000", "label": "Slot",
                                       "slot_id": "1"}]},
        )
        for value in variants:
            with self.subTest(value=value), self.assertRaises(ValueError):
                validate_colour_paint(value)
