"""Browsing an approved upstream catalogue does not require a typed search term."""
from unittest.mock import patch

from django.test import SimpleTestCase

from core.slicer_official_profiles import search_official_profiles
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
        with patch("core.slicer_prusa_official_profiles._sections", return_value={
            "Original Prusa MK4": ("printer_model:MK4", {})
        }):
            result = search_prusa_profiles("", "printer", "PrusaResearch")
        self.assertEqual(result["total_matches"], 1)

    def test_too_long_queries_remain_rejected(self):
        from core.slicer_official_profiles import OfficialProfileError
        with self.assertRaises(OfficialProfileError):
            search_bambu_native_profiles("x" * 81, "filament", "BBL")
