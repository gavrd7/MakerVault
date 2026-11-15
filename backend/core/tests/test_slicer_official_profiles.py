from unittest.mock import patch
from django.test import SimpleTestCase
from core.slicer_official_profiles import (
    OfficialProfileError, search_official_profiles, fetch_official_profile, available_official_vendors,
)


EXAMPLE = {
    "name": "Creality",
    "machine_list": [
        {"name": "Creality K1 (0.4 nozzle)", "sub_path": "machine/Creality K1 (0.4 nozzle).json"},
        {"name": "Creality K2 0.4 nozzle", "sub_path": "machine/Creality K2 0.4 nozzle.json"},
        {"name": "Bad", "sub_path": "../private.json"},
    ],
    "filament_list": [{"name": "Creality Generic PLA @K2-all", "sub_path": "filament/PLA K2.json"}],
    "process_list": [{"name": "0.20mm Standard @Creality K2 0.4 nozzle", "sub_path": "process/K2.json"}],
}


class OfficialOrcaProfileTests(SimpleTestCase):
    def test_read_only_search_matches_pinned_catalogue_only(self):
        with patch("core.slicer_official_profiles._manifest", return_value=EXAMPLE):
            result = search_official_profiles("K2", "printer")
            self.assertEqual(result["engine_version"], "2.4.2")
            self.assertEqual([item["name"] for item in result["profiles"]], ["Creality K2 0.4 nozzle"])
            self.assertEqual(result["import_status"], "candidate_only")
            self.assertFalse(any(x["name"] == "Bad" for x in result["profiles"]))

    def test_other_printer_catalogues_are_discoverable_and_searchable(self):
        vendors = {row["id"] for row in available_official_vendors()}
        for vendor in ("Voron", "Prusa", "Anycubic", "Elegoo", "Custom", "Qidi"):
            self.assertIn(vendor, vendors)
            with self.subTest(vendor=vendor):
                fixture = {**EXAMPLE, "name": vendor}
                with patch("core.slicer_official_profiles._manifest", return_value=fixture):
                    found = search_official_profiles("K2", "printer", vendor=vendor)
                    self.assertEqual(found["vendor"], vendor)
                    self.assertEqual(len(found["profiles"]), 1)

    def test_unknown_version_vendor_or_arbitrary_url_cannot_be_fetched(self):
        with patch("core.slicer_official_profiles._manifest", return_value=EXAMPLE):
            for name, path in (("Creality K2 0.4 nozzle", "https://evil.invalid/x"),
                               ("Other", "machine/Creality K2 0.4 nozzle.json"),
                               ("Bad", "../private.json")):
                with self.subTest(path=path), self.assertRaises(OfficialProfileError):
                    fetch_official_profile("printer", name, path)
            with self.assertRaises(OfficialProfileError):
                search_official_profiles("K2", "printer", vendor="Other")

    def test_profile_import_checks_name_and_native_kind(self):
        with patch("core.slicer_official_profiles._manifest", return_value=EXAMPLE):
            with patch("core.slicer_official_profiles._get_json",
                       return_value=({"name": "Creality K2 0.4 nozzle", "type": "machine"}, b'{"name":"Creality K2 0.4 nozzle","type":"machine"}')):
                raw = fetch_official_profile("printer", "Creality K2 0.4 nozzle",
                                             "machine/Creality K2 0.4 nozzle.json")
            self.assertIn(b"Creality K2", raw)
            with patch("core.slicer_official_profiles._get_json",
                       return_value=({"name": "Creality K2 0.4 nozzle", "type": "filament"}, b'{}')):
                with self.assertRaises(OfficialProfileError):
                    fetch_official_profile("printer", "Creality K2 0.4 nozzle",
                                           "machine/Creality K2 0.4 nozzle.json")

    def test_version_pinned_manufacturer_filament_catalogue(self):
        import core.slicer_official_profiles as official
        manifest = {
            "name": "OrcaFilamentLibrary",
            "machine_list": [],
            "process_list": [],
            "filament_list": [
                {"name": "fdm_filament_pla", "sub_path": "filament/base/fdm_filament_pla.json"},
                {"name": "eSUN PLA+ @base", "sub_path": "filament/eSUN/eSUN PLA+ @base.json"},
                {"name": "SUNLU PLA Matte @base", "sub_path": "filament/SUNLU/SUNLU PLA Matte @base.json"},
                {"name": "Invalid path", "sub_path": "filament/../../secret.json"},
            ],
        }
        with patch("core.slicer_official_profiles._manifest", return_value=manifest):
            self.assertEqual(official.official_filament_brands("2.5.0"), ["eSUN", "SUNLU"])
            result = official.search_official_profiles(
                "PLA", "filament", vendor="OrcaFilamentLibrary",
                printer_model="K2", version="2.5.0", brand="eSUN")
            self.assertEqual(result["engine_version"], "2.5.0")
            self.assertEqual(result["ref"], "v2.5.0")
            self.assertEqual([row["name"] for row in result["profiles"]], ["eSUN PLA+ @base"])
            with self.assertRaises(OfficialProfileError):
                official.search_official_profiles("PLA", "filament", "OrcaFilamentLibrary",
                                                 version="2.5.0", brand="../wrong")
            with self.assertRaises(OfficialProfileError):
                official.search_official_profiles("PLA", "filament", "OrcaFilamentLibrary",
                                                 version="2.6.0")

    def test_version_specific_source_is_never_silently_relabelled(self):
        import core.slicer_official_profiles as official
        expected = ("filament", "eSUN PLA+ @base", "filament/eSUN/eSUN PLA+ @base.json")
        manifest = {"name":"OrcaFilamentLibrary", "machine_list": [], "process_list": [],
                    "filament_list":[{"name":expected[1], "sub_path":expected[2]}]}
        raw = b'{"name":"eSUN PLA+ @base","type":"filament"}'
        with (patch("core.slicer_official_profiles._manifest", return_value=manifest),
              patch("core.slicer_official_profiles._get_json", return_value=({"name":expected[1], "type":"filament"},raw)) as fetch):
            self.assertEqual(official.fetch_official_profile(*expected,"OrcaFilamentLibrary",version="2.5.0"),raw)
            self.assertIn("/v2.5.0/",fetch.call_args.args[0])
