from unittest.mock import patch

from django.test import SimpleTestCase

from core.slicer_prusa_official_profiles import (
    _sections, official_catalogue_models, search_prusa_profiles, fetch_prusa_model,
)
from core.slicer_official_profiles import OfficialProfileError


class _Response:
    status_code = 200
    headers = {"Content-Length": "230"}

    def iter_content(self, size):
        yield (b"[vendor]\nname = Prusa Research\n"
               b"[printer_model:CORE_ONE]\nname = Prusa CORE One\n"
               b"bed_model = core_one_bed.stl\nbed_texture = core_one.svg\n"
               b"[printer_model:MK4S]\nname = Prusa MK4S\n"
               b"bed_model = mk4s_bed.stl\nbed_texture = mk4s.svg\n")

    def close(self):
        pass


class PrusaOfficialModelDiscoveryTests(SimpleTestCase):
    def tearDown(self):
        _sections.cache_clear()

    @patch("core.slicer_prusa_official_profiles.requests.get", return_value=_Response())
    def test_list_search_and_extract_one_model_without_printing_settings(self, get):
        models = official_catalogue_models()
        self.assertEqual(models, ["Prusa CORE One", "Prusa MK4S"])
        result = search_prusa_profiles("CORE", "printer")
        self.assertEqual(result["profiles"][0]["sub_path"], "PrusaResearch.ini")
        raw = fetch_prusa_model("printer", "Prusa CORE One", "PrusaResearch.ini")
        self.assertIn(b"bed_model = core_one_bed.stl", raw)
        self.assertNotIn(b"printer_model:MK4S", raw)
        self.assertIn("version_2.9.6/resources/profiles/PrusaResearch.ini",
                      get.call_args.args[0])

    @patch("core.slicer_prusa_official_profiles.requests.get", return_value=_Response())
    def test_rejects_nonindexed_selection_and_nonprinter_import(self, get):
        with self.assertRaises(OfficialProfileError):
            fetch_prusa_model("printer", "Unknown Model", "PrusaResearch.ini")
        with self.assertRaises(OfficialProfileError):
            search_prusa_profiles("Prusa", "process")
        with self.assertRaises(OfficialProfileError):
            fetch_prusa_model("printer", "Prusa MK4S", "../other.ini")
