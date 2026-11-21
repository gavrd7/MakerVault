from django.test import SimpleTestCase
from core.slicer_support_painting import validate_support_paint


class SupportPaintDraftTests(SimpleTestCase):
    def setUp(self):
        self.payload = {"version": 2, "signature": "2:abcdef01",
                        "regions": [{"slot": 0, "patches": [{
                            "face": 0, "polygon": [[0, 0, 0], [2, 0, 0], [0, 2, 0]],
                        }]}]}

    def test_round_trip_preserves_enforcers_and_blockers_without_filaments(self):
        result = validate_support_paint(self.payload)
        self.assertEqual(result["regions"][0]["slot"], 0)
        self.assertNotIn("palette", result)
        result["regions"].append({"slot": 1, "patches": [{
            "face": 1, "polygon": [[0, 0, 0], [2, 0, 0], [0, 2, 0]],
        }]})
        self.assertEqual(validate_support_paint(result)["regions"][1]["slot"], 1)

    def test_invalid_support_actions_and_geometry_are_rejected(self):
        for item in (
            {**self.payload, "version": 1},
            {**self.payload, "palette": []},
            {**self.payload, "regions": [{**self.payload["regions"][0], "slot": 2}]},
            {**self.payload, "regions": [{**self.payload["regions"][0],
                "patches": [{"face": 9, "polygon": [[0, 0, 0]] * 3}]}]},
        ):
            with self.subTest(item=item), self.assertRaises(ValueError):
                validate_support_paint(item)
