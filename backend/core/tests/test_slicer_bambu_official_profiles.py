from unittest.mock import patch

from django.test import SimpleTestCase

from core.slicer_bambu_official_profiles import (
    _entries, official_catalogue_models, search_bambu_profiles, fetch_bambu_model,
)
from core.slicer_official_profiles import OfficialProfileError


class BambuOfficialModelDiscoveryTests(SimpleTestCase):
    def tearDown(self):
        _entries.cache_clear()

    @patch("core.slicer_bambu_official_profiles._get_json")
    def test_catalogue_searches_current_models_not_a_hardcoded_printer_list(self, fetch):
        fetch.return_value = ({
            "machine_model_list": [
                {"name": "Bambu Lab H2D", "sub_path": "machine/Bambu Lab H2D.json"},
                {"name": "Bambu Lab P2S", "sub_path": "machine/Bambu Lab P2S.json"},
                {"name": "Malicious", "sub_path": "machine/../../unsafe.json"},
            ],
        }, b"")
        self.assertEqual(official_catalogue_models(), ["Bambu Lab H2D", "Bambu Lab P2S"])
        result = search_bambu_profiles("P2S", "printer")
        self.assertEqual([item["name"] for item in result["profiles"]], ["Bambu Lab P2S"])
        self.assertTrue(result["model_artwork_only"])

    @patch("core.slicer_bambu_official_profiles._get_json")
    def test_rejects_nonmodel_file_and_unindexed_candidate(self, fetch):
        fetch.side_effect = [
            ({"machine_model_list": [
                {"name": "Bambu Lab H2D", "sub_path": "machine/Bambu Lab H2D.json"},
            ]}, b""),
            ({"name": "Wrong Name", "type": "machine_model"}, b"{}"),
        ]
        with self.assertRaises(OfficialProfileError):
            fetch_bambu_model("printer", "Unknown", "machine/Unknown.json")
        with self.assertRaises(OfficialProfileError):
            fetch_bambu_model("printer", "Bambu Lab H2D", "machine/Bambu Lab H2D.json")

    @patch("core.slicer_bambu_official_profiles._get_json")
    def test_imported_model_is_candidate_not_execution_approval(self, fetch):
        raw = b'{"name":"Bambu Lab H2D","type":"machine_model","bed_texture":"plate.svg"}'
        fetch.side_effect = [
            ({"machine_model_list": [
                {"name": "Bambu Lab H2D", "sub_path": "machine/Bambu Lab H2D.json"},
            ]}, b""),
            ({"name": "Bambu Lab H2D", "type": "machine_model"}, raw),
        ]
        self.assertEqual(fetch_bambu_model("printer", "Bambu Lab H2D",
                                           "machine/Bambu Lab H2D.json"), raw)
        with self.assertRaises(OfficialProfileError):
            search_bambu_profiles("H2D", "process")
