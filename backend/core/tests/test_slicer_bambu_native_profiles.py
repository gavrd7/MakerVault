"""Official Bambu Studio native preset search/import safety, no network."""
import json
from unittest.mock import patch
from django.test import SimpleTestCase

from core.slicer_bambu_native_profiles import (
    _entries, search_bambu_native_profiles, fetch_bambu_native_chain,
    ENGINE_VERSION,
)
from core.slicer_official_profiles import OfficialProfileError


class BambuNativeProfileImportTests(SimpleTestCase):
    def tearDown(self):
        _entries.cache_clear()

    def _index(self):
        return {
            "machine_list": [
                {"name": "Bambu Lab X1 Carbon 0.4 nozzle",
                 "sub_path": "machine/Bambu Lab X1 Carbon 0.4 nozzle.json"},
                {"name": "fdm_base", "sub_path": "machine/fdm_base.json"},
                {"name": "Bambu Lab X1 Carbon 0.4 nozzle template machine_start_gcode",
                 "sub_path": "machine/Bambu Lab X1 Carbon 0.4 nozzle template machine_start_gcode.json"},
                {"name": "Attack", "sub_path": "machine/../../outside.json"},
            ],
            "process_list": [
                {"name": "0.20mm Standard @BBL X1C",
                 "sub_path": "process/0.20mm Standard @BBL X1C.json"},
            ],
            "filament_list": [
                {"name": "Bambu PLA Basic @BBL X1C",
                 "sub_path": "filament/Bambu PLA Basic @BBL X1C.json"},
            ],
        }

    def _data(self):
        return {
            "machine/Bambu Lab X1 Carbon 0.4 nozzle.json": {
                "type": "machine", "name": "Bambu Lab X1 Carbon 0.4 nozzle",
                "instantiation": "true", "inherits": "fdm_base",
                "include": ["Bambu Lab X1 Carbon 0.4 nozzle template machine_start_gcode"],
            },
            "machine/fdm_base.json": {
                "type": "machine", "name": "fdm_base",
                "instantiation": "false", "nozzle_diameter": ["0.4"],
            },
            "machine/Bambu Lab X1 Carbon 0.4 nozzle template machine_start_gcode.json": {
                "name": "Bambu Lab X1 Carbon 0.4 nozzle template machine_start_gcode",
                "instantiation": "false", "machine_start_gcode": "G28",
            },
            "process/0.20mm Standard @BBL X1C.json": {
                "type": "process", "name": "0.20mm Standard @BBL X1C",
                "instantiation": "true", "layer_height": "0.2",
            },
            "filament/Bambu PLA Basic @BBL X1C.json": {
                "type": "filament", "name": "Bambu PLA Basic @BBL X1C",
                "instantiation": "true", "filament_type": ["PLA"],
            },
        }

    def _mock_get(self, url, limit):
        if url.endswith("/BBL.json"):
            doc = self._index()
        else:
            key = url.split("/BBL/", 1)[1]
            doc = self._data()[key]
        raw = json.dumps(doc).encode("utf-8")
        return doc, raw

    @patch("core.slicer_bambu_native_profiles._get_json")
    def test_p1s_profiles_are_visible_without_an_owned_printer_filter(self, fetch):
        index = self._index()
        index["machine_list"].extend([
            {"name": "Bambu Lab P1S 0.4 nozzle",
             "sub_path": "machine/Bambu Lab P1S 0.4 nozzle.json"},
            {"name": "Bambu Lab P1S 0.6 nozzle",
             "sub_path": "machine/Bambu Lab P1S 0.6 nozzle.json"},
        ])
        fetch.side_effect = lambda url, limit: (index, json.dumps(index).encode())
        found = search_bambu_native_profiles("P1S", "printer", vendor="BBL")
        self.assertEqual(found["total_matches"], 2)
        self.assertEqual(len(found["profiles"]), 2)

    @patch("core.slicer_bambu_native_profiles._get_json")
    def test_creality_catalogue_is_not_blocked_by_bambu_engine(self, fetch):
        index = {"machine_list": [
            {"name": "Creality K1 0.4 nozzle",
             "sub_path": "machine/Creality K1 0.4 nozzle.json"},
        ], "filament_list": [], "process_list": []}
        fetch.side_effect = lambda url, limit: (index, json.dumps(index).encode())
        found = search_bambu_native_profiles("", "printer", vendor="Creality")
        self.assertEqual(found["profiles"][0]["name"], "Creality K1 0.4 nozzle")
        self.assertEqual(found["vendor"], "Creality")

    @patch("core.slicer_bambu_native_profiles._get_json")
    def test_searches_real_native_machine_process_filament_not_model_artwork(self, fetch):
        fetch.side_effect = self._mock_get
        printer = search_bambu_native_profiles("X1 Carbon", "printer")
        self.assertEqual([r["name"] for r in printer["profiles"]],
                         ["Bambu Lab X1 Carbon 0.4 nozzle"])
        self.assertFalse(printer["model_artwork_only"])
        process = search_bambu_native_profiles("Standard", "process")
        self.assertEqual(len(process["profiles"]), 1)
        filament = search_bambu_native_profiles("PLA Basic", "filament")
        self.assertEqual(len(filament["profiles"]), 1)
        self.assertNotIn("Attack", _entries("printer"))

    @patch("core.slicer_bambu_native_profiles._get_json")
    def test_imports_verified_complete_machine_chain_including_typeless_template(self, fetch):
        fetch.side_effect = self._mock_get
        chain = fetch_bambu_native_chain(
            "printer", "Bambu Lab X1 Carbon 0.4 nozzle",
            "machine/Bambu Lab X1 Carbon 0.4 nozzle.json")
        self.assertEqual([item[0] for item in chain], [
            "fdm_base",
            "Bambu Lab X1 Carbon 0.4 nozzle template machine_start_gcode",
            "Bambu Lab X1 Carbon 0.4 nozzle",
        ])
        self.assertEqual(json.loads(chain[-1][2])["type"], "machine")

    @patch("core.slicer_bambu_native_profiles._get_json")
    def test_rejects_arbitrary_path_unknown_release_and_uninstantiable_root(self, fetch):
        fetch.side_effect = self._mock_get
        with self.assertRaisesRegex(OfficialProfileError, "pinned vendor index"):
            fetch_bambu_native_chain("printer", "Attack", "machine/../../outside.json")
        with self.assertRaisesRegex(OfficialProfileError, "reviewed exact"):
            fetch_bambu_native_chain(
                "printer", "Bambu Lab X1 Carbon 0.4 nozzle",
                "machine/Bambu Lab X1 Carbon 0.4 nozzle.json", version="02.10.00.00")
        with self.assertRaisesRegex(OfficialProfileError, "instantiable"):
            fetch_bambu_native_chain("printer", "fdm_base", "machine/fdm_base.json")

    @patch("core.slicer_bambu_native_profiles._get_json")
    def test_rejects_cycle_and_wrong_typed_include(self, fetch):
        def cycle_fetch(url, limit):
            doc, raw = self._mock_get(url, limit)
            if url.endswith("machine/fdm_base.json"):
                doc = {**doc, "inherits": "Bambu Lab X1 Carbon 0.4 nozzle"}
                raw = json.dumps(doc).encode()
            return doc, raw
        fetch.side_effect = cycle_fetch
        with self.assertRaisesRegex(OfficialProfileError, "circular"):
            fetch_bambu_native_chain(
                "printer", "Bambu Lab X1 Carbon 0.4 nozzle",
                "machine/Bambu Lab X1 Carbon 0.4 nozzle.json")
        _entries.cache_clear()
        def wrong_type(url, limit):
            doc, raw = self._mock_get(url, limit)
            if url.endswith("template machine_start_gcode.json"):
                doc = {**doc, "type": "filament"}
                raw = json.dumps(doc).encode()
            return doc, raw
        fetch.side_effect = wrong_type
        with self.assertRaisesRegex(OfficialProfileError, "identity mismatch"):
            fetch_bambu_native_chain(
                "printer", "Bambu Lab X1 Carbon 0.4 nozzle",
                "machine/Bambu Lab X1 Carbon 0.4 nozzle.json")
