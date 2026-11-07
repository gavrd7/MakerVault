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
