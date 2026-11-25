from unittest.mock import patch

from django.test import SimpleTestCase

from core.slicer_prusa_official_profiles import (
    _sections, _native_sections, official_catalogue_models,
    search_prusa_profiles, fetch_prusa_model, fetch_prusa_profile,
)
from core.slicer_official_profiles import OfficialProfileError


class _Response:
    status_code = 200
    headers = {"Content-Length": "720"}

    def iter_content(self, size):
        yield (b"[vendor]\nname = Prusa Research\n"
               b"[printer_model:CORE_ONE]\nname = Prusa CORE One\n"
               b"bed_model = core_one_bed.stl\nbed_texture = core_one.svg\n"
               b"[printer_model:MK4S]\nname = Prusa MK4S\n"
               b"bed_model = mk4s_bed.stl\nbed_texture = mk4s.svg\n"
               b"[printer:*common*]\nprinter_technology = FFF\n"
               b"nozzle_diameter = 0.4\nbed_shape = 0x0,250x0,250x210,0x210\n"
               b"[printer:Original Prusa MK4S]\ninherits = *common*\n"
               b"printer_model = MK4S\n"
               b"[filament:*common*]\nfilament_diameter = 1.75\n"
               b"[filament:Generic PLA]\ninherits = *common*\n"
               b"temperature = 215\n"
               b"[print:*common*]\nlayer_height = 0.2\n"
               b"post_process = \nfill_density = 15%\n"
               b"[print:0.20mm NORMAL]\ninherits = *common*\n"
               b"fill_density = 20%\n")

    def close(self):
        pass


class PrusaOfficialModelDiscoveryTests(SimpleTestCase):
    def tearDown(self):
        _sections.cache_clear()
        _native_sections.cache_clear()

    @patch("core.slicer_prusa_official_profiles.requests.get", return_value=_Response())
    def test_artwork_models_remain_separate_from_native_profiles(self, get):
        models = official_catalogue_models()
        self.assertEqual(models, ["Prusa CORE One", "Prusa MK4S"])
        raw = fetch_prusa_model("printer", "Prusa CORE One", "PrusaResearch.ini")
        self.assertIn(b"bed_model = core_one_bed.stl", raw)
        self.assertNotIn(b"printer_model:MK4S", raw)
        self.assertIn("450d70dd81c9b8990bc6bc8e690e31f82ddceb11/resources/profiles/PrusaResearch.ini",
                      get.call_args.args[0])

    @patch("core.slicer_prusa_official_profiles.requests.get", return_value=_Response())
    def test_native_search_and_flatten_all_three_profile_kinds(self, get):
        for kind, query, expected in (
            ("printer", "MK4S", "Original Prusa MK4S"),
            ("filament", "PLA", "Generic PLA"),
            ("process", "NORMAL", "0.20mm NORMAL"),
        ):
            with self.subTest(kind=kind):
                result = search_prusa_profiles(query, kind)
                self.assertEqual(result["profiles"][0]["name"], expected)
                self.assertEqual(result["profiles"][0]["sub_path"], "PrusaResearch.ini")
                self.assertFalse(result["model_artwork_only"])
                self.assertTrue(result["compatibility_not_verified"])
                raw = fetch_prusa_profile(kind, expected, "PrusaResearch.ini")
                self.assertIn(b" = ", raw)
                self.assertNotIn(b"inherits = ", raw)
                self.assertNotIn(b"[printer:", raw)
                if kind == "printer":
                    self.assertIn(b"nozzle_diameter = 0.4", raw)
                    self.assertIn(b"printer_technology = FFF", raw)
                if kind == "filament":
                    self.assertIn(b"filament_diameter = 1.75", raw)
                if kind == "process":
                    self.assertIn(b"layer_height = 0.2", raw)
                    self.assertIn(b"fill_density = 20%", raw)

    @patch("core.slicer_prusa_official_profiles.requests.get", return_value=_Response())
    def test_internal_parents_hidden_from_search(self, get):
        rows = search_prusa_profiles("", "printer")
        self.assertEqual(rows["total_matches"], 1)
        self.assertEqual(rows["profiles"][0]["name"], "Original Prusa MK4S")

    def test_native_prusa_catalogue_has_stable_pages_beyond_forty(self):
        sections = {f"filament:PLA {i:03d}": {"temperature": "210"}
                    for i in range(95)}
        with patch("core.slicer_prusa_official_profiles._native_sections",
                   return_value=sections):
            pages = [search_prusa_profiles("PLA", "filament", offset=i)
                     for i in (0, 40, 80)]
        self.assertEqual([len(p["profiles"]) for p in pages], [40, 40, 15])
        self.assertTrue(all(p["total_matches"] == 95 for p in pages))
        self.assertEqual(pages[0]["profiles"][0]["name"], "PLA 000")
        self.assertEqual(pages[1]["profiles"][0]["name"], "PLA 040")
        self.assertEqual(pages[2]["profiles"][-1]["name"], "PLA 094")

    @patch("core.slicer_prusa_official_profiles.requests.get", return_value=_Response())
    def test_rejects_unapproved_selection_and_nonindexed_artwork(self, get):
        with self.assertRaises(OfficialProfileError):
            fetch_prusa_model("printer", "Unknown Model", "PrusaResearch.ini")
        with self.assertRaises(OfficialProfileError):
            search_prusa_profiles("Prusa", "unsupported")
        with self.assertRaises(OfficialProfileError):
            fetch_prusa_profile("printer", "Original Prusa MK4S", "../other.ini")
        with self.assertRaises(OfficialProfileError):
            fetch_prusa_profile("filament", "Original Prusa MK4S", "PrusaResearch.ini")

    def test_real_prusa_multi_parent_resolution_order(self):
        sections = {
            "print:Base": {"layer_height": "0.2", "fill_density": "10%"},
            "print:A": {"inherits": "Base", "fill_density": "20%"},
            "print:B": {"inherits": "Base", "fill_density": "30%"},
            "print:Derived": {"inherits": "A; B", "perimeters": "3"},
        }
        with patch("core.slicer_prusa_official_profiles._native_sections",
                   return_value=sections):
            raw = fetch_prusa_profile("process", "Derived", "PrusaResearch.ini")
        self.assertIn(b"fill_density = 30%", raw)
        self.assertIn(b"layer_height = 0.2", raw)
        self.assertNotIn(b"inherits", raw)

    def test_rejects_unresolved_parent_script_and_nonfff(self):
        for sections, kind, name in (
            ({"printer:Unsafe": {"inherits": "Unknown", "nozzle_diameter": "0.4",
                                 "bed_shape": "0x0,200x0,200x200,0x200"}},
             "printer", "Unsafe"),
            ({"print:Unsafe": {"layer_height": "0.2",
                               "post_process": "UNTRUSTED_COMMAND_MUST_NOT_RUN"}},
             "process", "Unsafe"),
            ({"printer:SLA": {"printer_technology": "SLA",
                              "nozzle_diameter": "0.4", "bed_shape": "0x0,20x0"}},
             "printer", "SLA"),
        ):
            with self.subTest(name=name):
                with patch("core.slicer_prusa_official_profiles._native_sections",
                           return_value=sections):
                    with self.assertRaises(OfficialProfileError):
                        fetch_prusa_profile(kind, name, "PrusaResearch.ini")
