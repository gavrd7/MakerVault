from unittest.mock import patch
from django.test import SimpleTestCase

from core.slicer_creality_official_profiles import (
    OfficialProfileError, fetch_creality_profile, search_creality_profiles, available_creality_vendors,
)


class PinnedCrealityProfileTests(SimpleTestCase):
    def setUp(self):
        self.manifest = {
            "name": "Creality", "machine_list": [
                {"name": "Creality K1 0.4 nozzle", "sub_path": "machine/Creality K1 0.4 nozzle.json"},
                {"name": "Creality K2 0.4 nozzle", "sub_path": "machine/Creality K2 0.4 nozzle.json"},
                {"name": "Bad traversal", "sub_path": "../private.json"},
            ],
            "filament_list": [{"name": "Hyper PLA", "sub_path": "filament/Hyper PLA.json"}],
            "process_list": [{"name": "0.20 Standard", "sub_path": "process/0.20 Standard.json"}],
        }

    @patch("core.slicer_creality_official_profiles._manifest")
    def test_k1_k2_are_available_from_creality_not_orca_catalogue(self, manifest):
        manifest.return_value = self.manifest
        found = search_creality_profiles("Creality", "printer")
        self.assertEqual(found["engine"], "crealityprint")
        self.assertEqual(found["engine_version"], "7.3.0")
        self.assertEqual(found["total_matches"], 2)
        self.assertFalse(any("private" in row["sub_path"] for row in found["profiles"]))

    @patch("core.slicer_creality_official_profiles._manifest")
    def test_cross_manufacturer_pinned_catalogue_search(self, manifest):
        vendors = {row["id"] for row in available_creality_vendors()}
        self.assertTrue({"Prusa", "Voron", "Anycubic", "Elegoo", "Custom"} <= vendors)
        manifest.return_value = {
            **self.manifest,
            "name": "Prusa",
            "machine_list": [{"name": "Prusa MK4 0.4 nozzle", "sub_path": "machine/Prusa MK4 0.4 nozzle.json"}],
        }
        found = search_creality_profiles("MK4", "printer", vendor="Prusa")
        self.assertEqual(found["vendor"], "Prusa")
        self.assertEqual(found["profiles"][0]["name"], "Prusa MK4 0.4 nozzle")
        self.assertEqual(manifest.call_args.args, ("Prusa",))

    @patch("core.slicer_creality_official_profiles._get_json")
    @patch("core.slicer_creality_official_profiles._manifest")
    def test_prusa_native_profile_uses_crealityprint_not_orca_source(self, manifest, get):
        manifest.return_value = {
            **self.manifest,
            "name": "Prusa",
            "machine_list": [{"name": "Prusa MK4 0.4 nozzle", "sub_path": "machine/Prusa MK4 0.4 nozzle.json"}],
        }
        get.return_value = (
            {"type": "machine", "name": "Prusa MK4 0.4 nozzle", "inherits": "fdm_machine_common"},
            b'{"type":"machine","name":"Prusa MK4 0.4 nozzle","inherits":"fdm_machine_common"}',
        )
        raw = fetch_creality_profile("printer", "Prusa MK4 0.4 nozzle",
                                     "machine/Prusa MK4 0.4 nozzle.json", "Prusa")
        self.assertIn(b"fdm_machine_common", raw)
        self.assertIn("CrealityOfficial/CrealityPrint/v7.3.0/resources/profiles/Prusa/",
                      get.call_args.args[0])
        with self.assertRaises(OfficialProfileError):
            fetch_creality_profile("printer", "Prusa MK4 0.4 nozzle",
                                  "machine/Prusa MK4 0.4 nozzle.json", "Nonexistent")

    @patch("core.slicer_creality_official_profiles._get_json")
    @patch("core.slicer_creality_official_profiles._manifest")
    def test_import_is_pinned_and_rejects_wrong_type(self, manifest, get):
        manifest.return_value = self.manifest
        get.return_value = ({"type": "machine", "inherits": "fdm_creality_common"}, b'{"type":"machine"}')
        raw = fetch_creality_profile(
            "printer", "Creality K1 0.4 nozzle", "machine/Creality K1 0.4 nozzle.json"
        )
        self.assertEqual(raw, b'{"type":"machine"}')
        self.assertIn("/v7.3.0/resources/profiles/Creality/", get.call_args.args[0])
        with self.assertRaises(OfficialProfileError):
            fetch_creality_profile("printer", "Creality K1 0.4 nozzle", "../private.json")
        get.return_value = ({"type": "filament"}, b'{}')
        with self.assertRaises(OfficialProfileError):
            fetch_creality_profile(
                "printer", "Creality K1 0.4 nozzle", "machine/Creality K1 0.4 nozzle.json"
            )

