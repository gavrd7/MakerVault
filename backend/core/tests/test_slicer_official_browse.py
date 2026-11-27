"""Browsing an approved upstream catalogue does not require a typed search term."""
from unittest.mock import patch

from django.test import SimpleTestCase

from core.slicer_official_profiles import (search_official_profiles,
    search_all_official_filaments, all_official_filament_manufacturers,
    OfficialProfileError)
from core.slicer_creality_official_profiles import search_creality_profiles
from core.slicer_bambu_native_profiles import search_bambu_native_profiles
from core.slicer_snapmaker_official_profiles import search_snapmaker_profiles
from core.slicer_prusa_official_profiles import search_prusa_profiles


class OfficialCatalogueBrowseTests(SimpleTestCase):
    def test_orca_browse_without_query_keeps_limit_and_optional_model_filter(self):
        entries = [(f"Sample {i}", f"machine/Sample {i}.json") for i in range(42)]
        with patch("core.slicer_official_profiles._entries", return_value=entries):
            result = search_official_profiles("", "printer", "Creality")
        self.assertEqual(result["total_matches"], 42)
        self.assertEqual(len(result["profiles"]), 40)

    def test_unified_orca_filament_brands_include_printer_manufacturer_catalogues(self):
        with patch("core.slicer_official_profiles.official_filament_brands",
                   return_value=["3D-Fuel", "Creality", "eSUN"]):
            brands = all_official_filament_manufacturers("2.5.0")
        self.assertIn("Creality", brands)
        self.assertIn("Elegoo", brands)
        self.assertIn("eSUN", brands)
        self.assertEqual(brands.count("Creality"), 1)
        self.assertEqual(brands, sorted(brands, key=str.casefold))

    def test_unified_orca_filaments_keep_source_vendor_and_page_across_catalogues(self):
        def entries(vendor, kind, version):
            self.assertEqual((kind, version), ("filament", "2.5.0"))
            if vendor == "OrcaFilamentLibrary":
                return [("Creality PLA @ System", "filament/Creality/PLA.json"),
                        ("eSUN PLA @ System", "filament/eSUN/PLA.json")]
            if vendor == "Creality":
                return [(f"Creality PLA K2 {i}", f"filament/K2/{i}.json")
                        for i in range(90)]
            if vendor == "Elegoo":
                return [("Elegoo PLA", "filament/PLA.json")]
            return []
        with patch("core.slicer_official_profiles._entries", side_effect=entries), \
             patch("core.slicer_official_profiles.official_filament_brands",
                   return_value=["Creality", "eSUN"]):
            result = search_all_official_filaments(
                "PLA", brand="Creality", version="2.5.0")
            second = search_all_official_filaments(
                "PLA", brand="Creality", version="2.5.0", offset=40)
            self.assertEqual(result["total_matches"], 91)
            self.assertEqual(len(result["profiles"]), 40)
            self.assertEqual(len(second["profiles"]), 40)
            self.assertEqual(len(set((p["vendor"], p["sub_path"])
                                  for p in result["profiles"])), 40)
            self.assertTrue(all(p["vendor"] in
                {"Creality", "OrcaFilamentLibrary"}
                for p in result["profiles"]))
            all_results = search_all_official_filaments(
                "PLA", version="2.5.0")
        self.assertEqual(all_results["total_matches"], 94)
        self.assertEqual(all_results["partial_catalogues"], 0)
        self.assertIn("Elegoo", {
            p["vendor"] for p in all_results["profiles"]} |
            {"Elegoo" if all_results["total_matches"] == 94 else ""})

    def test_unified_filament_search_rejects_unlisted_brands_without_network(self):
        with patch("core.slicer_official_profiles.official_filament_brands",
                   return_value=["eSUN"]), \
             patch("core.slicer_official_profiles._entries") as entries:
            with self.assertRaisesRegex(OfficialProfileError, "manufacturer"):
                search_all_official_filaments(brand="../../private", version="2.5.0")
            entries.assert_not_called()

    def test_creality_browse_without_query(self):
        with patch("core.slicer_creality_official_profiles._entries", return_value=[
            ("Creality K2", "machine/k2.json")
        ]):
            result = search_creality_profiles("", "printer", "Creality")
        self.assertEqual(result["total_matches"], 1)

    def test_bambu_browse_without_query(self):
        with patch("core.slicer_bambu_native_profiles._entries", return_value={
            "Generic PLA": "filament/Generic PLA.json",
            "fdm_internal": "filament/fdm_internal.json",
        }):
            result = search_bambu_native_profiles("", "filament", "BBL")
        self.assertEqual([row["name"] for row in result["profiles"]], ["Generic PLA"])

    def test_snapmaker_browse_without_query(self):
        with patch("core.slicer_snapmaker_official_profiles._entries", return_value=[
            ("Snapmaker U1", "machine/Snapmaker U1.json")
        ]):
            result = search_snapmaker_profiles("", "printer", "Snapmaker")
        self.assertEqual(result["total_matches"], 1)

    def test_prusa_browse_without_query(self):
        with patch("core.slicer_prusa_official_profiles._native_sections", return_value={
            "printer:Original Prusa MK4": {"nozzle_diameter": "0.4"}
        }):
            result = search_prusa_profiles("", "printer", "PrusaResearch")
        self.assertEqual(result["total_matches"], 1)

    def test_too_long_queries_remain_rejected(self):
        from core.slicer_official_profiles import OfficialProfileError
        with self.assertRaises(OfficialProfileError):
            search_bambu_native_profiles("x" * 81, "filament", "BBL")
