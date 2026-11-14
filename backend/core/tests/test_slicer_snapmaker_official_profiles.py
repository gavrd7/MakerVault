from unittest.mock import patch

from django.test import SimpleTestCase

from core.slicer_snapmaker_official_profiles import (
    _manifest, _entries, official_catalogue_models,
    search_snapmaker_profiles, fetch_snapmaker_profile,
)
from core.slicer_official_profiles import OfficialProfileError


class SnapmakerOfficialProfilesTests(SimpleTestCase):
    def tearDown(self):
        _manifest.cache_clear()

    @patch("core.slicer_snapmaker_official_profiles._get_json")
    def test_uses_manifest_for_search_and_profile_import(self, fetch):
        fetch.side_effect = [
            ({"machine_list": [
                {"name": "Snapmaker U1 0.4 nozzle",
                 "sub_path": "machine/Snapmaker U1 0.4 nozzle.json"},
                {"name": "Unsafe", "sub_path": "machine/../bad.json"},
            ], "process_list": [], "filament_list": []}, b""),
            ({"type": "machine", "name": "Snapmaker U1 0.4 nozzle"},
             b'{"type":"machine","name":"Snapmaker U1 0.4 nozzle"}'),
        ]
        results = search_snapmaker_profiles("U1", "printer")
        self.assertEqual(len(results["profiles"]), 1)
        path = results["profiles"][0]["sub_path"]
        raw = fetch_snapmaker_profile("printer", "Snapmaker U1 0.4 nozzle", path)
        self.assertIn(b"Snapmaker U1", raw)
        self.assertEqual(fetch.call_count, 2)

    @patch("core.slicer_snapmaker_official_profiles._get_json")
    def test_unknown_source_or_subpath_rejected(self, fetch):
        fetch.return_value = ({"machine_list": [], "process_list": [], "filament_list": []}, b"")
        with self.assertRaises(OfficialProfileError):
            fetch_snapmaker_profile("printer", "User Invented", "machine/User Invented.json")
        with self.assertRaises(OfficialProfileError):
            search_snapmaker_profiles("U1", "unknown")
