import json
from types import SimpleNamespace
from unittest.mock import patch

from django.test import SimpleTestCase

from core.slicer_native_overrides import apply_orca_job_overrides, ORCA_PLATES
from core.slicer_plate_types import inspect_native_plates, effective_orca_plate, native_plate_key


class NativeSlicerPlateAndColourTests(SimpleTestCase):
    def setUp(self):
        self.temperatures = {
            "cool_plate_temp": ["35"],
            "eng_plate_temp": ["65"],
            "hot_plate_temp": ["70"],
            "textured_plate_temp": ["65"],
            "textured_cool_plate_temp": ["45"],
            "supertack_plate_temp": ["50"],
        }

    def test_explicit_plate_selects_matching_native_temperature_without_changing_source(self):
        process = json.dumps({"name": "K2 0.20", "layer_height": "0.2"}).encode()
        filament = json.dumps({"name":"PLA", **self.temperatures}).encode()
        for plate_type, native_name in ORCA_PLATES.items():
            if native_name is None:
                continue
            with self.subTest(plate_type=plate_type):
                p, f = apply_orca_job_overrides(process, filament, plate_type, [])
                result = json.loads(p)
                self.assertEqual(result["curr_bed_type"], native_name)
                self.assertEqual(json.loads(f)["cool_plate_temp"], ["35"])
                self.assertEqual(json.loads(f)["textured_plate_temp"], ["65"])
        self.assertNotIn("curr_bed_type", json.loads(process))

    def test_native_machine_model_default_wins_over_stale_process_cool_plate(self):
        process = json.dumps({"name":"Standard",
                              "curr_bed_type":"Cool Plate"}).encode()
        filament = json.dumps(self.temperatures).encode()
        with patch("core.slicer_native_overrides.effective_orca_plate",
                   return_value="textured_pei") as resolved:
            p, _ = apply_orca_job_overrides(process, filament, "default", [],
                                            printer_profile=SimpleNamespace(pk="machine"))
        self.assertEqual(json.loads(p)["curr_bed_type"], "Textured PEI Plate")
        resolved.assert_called_once()

    def test_real_native_k2_machine_model_default_is_textured_pei(self):
        source=SimpleNamespace(
            engine="orcaslicer", engine_version="2.5.0",
            provenance=("OrcaSlicer/OrcaSlicer@v2.5.0/Creality/"
                        "machine/Creality K2 0.4 nozzle.json"),
        )
        with patch("core.slicer_plate_types.resolved_native_profile",
                   return_value=b'{"printer_model":"Creality K2","support_multi_bed_types":"1"}'), \
             patch("core.slicer_plate_types._official_machine_model",
                   return_value={"type":"machine_model","name":"Creality K2",
                                 "default_bed_type":"Textured PEI Plate"}) as fetch:
            metadata=inspect_native_plates(source)
            resolved=effective_orca_plate("default", {"curr_bed_type":"Cool Plate"}, source)
        self.assertEqual(metadata["default"],"textured_pei")
        self.assertIn("textured_pei",metadata["supported"])
        self.assertEqual(resolved,"textured_pei")
        self.assertGreaterEqual(fetch.call_count,1)

    def test_numeric_native_default_and_excluded_bed_types(self):
        self.assertEqual(native_plate_key("4"), "textured_pei")
        self.assertEqual(native_plate_key(4), "textured_pei")
        self.assertIsNone(native_plate_key("0"))
        source=SimpleNamespace(engine="orcaslicer", engine_version="2.5.0", provenance="")
        with patch("core.slicer_plate_types.resolved_native_profile",
                   return_value=b'{"default_bed_type":"4","support_multi_bed_types":"1","not_support_bed_types":[1,2]}'):
            metadata=inspect_native_plates(source)
        self.assertEqual(metadata["default"], "textured_pei")
        self.assertNotIn("cool", metadata["supported"])
        self.assertNotIn("engineering", metadata["supported"])
        self.assertIn("textured_pei", metadata["supported"])

    def test_single_model_selected_white_is_sent_to_native_filament(self):
        process = b'{"name":"Standard"}'
        filament = json.dumps({"default_filament_colour":["#F2754E"],
                               **self.temperatures}).encode()
        p, f = apply_orca_job_overrides(process, filament, "textured_pei", [
            {"asset_id": "1", "color": "#ffffff"},
        ])
        self.assertEqual(json.loads(p)["curr_bed_type"], "Textured PEI Plate")
        self.assertEqual(json.loads(p)["filament_colour"], ["#FFFFFF"])
        self.assertEqual(json.loads(f)["default_filament_colour"], ["#FFFFFF"])

    def test_multiple_colours_do_not_invent_multimaterial_mappings(self):
        p, f = apply_orca_job_overrides(
            b'{"name":"Standard","curr_bed_type":"Textured PEI Plate"}',
            json.dumps({"default_filament_colour":["#F2754E"],
                        **self.temperatures}).encode(),
            "default",
            [{"color": "#FFFFFF"}, {"color": "#000000"}],
        )
        self.assertNotIn("filament_colour", json.loads(p))
        self.assertEqual(json.loads(f)["default_filament_colour"], ["#F2754E"])

    def test_unknown_native_default_and_missing_selected_plate_heater_fail_closed(self):
        with self.assertRaisesRegex(ValueError,"default build plate is unknown"):
            apply_orca_job_overrides(b'{"name":"Standard"}',
                json.dumps(self.temperatures).encode(), "default", [])
        with self.assertRaisesRegex(ValueError,"does not declare a temperature"):
            apply_orca_job_overrides(b'{"name":"Standard"}',
                b'{"cool_plate_temp":["35"]}', "textured_pei", [])
        with self.assertRaisesRegex(ValueError,"plate"):
            apply_orca_job_overrides(b"{}", b"{}", "unknown", [])
        with self.assertRaises(ValueError):
            apply_orca_job_overrides(b"[]", b"{}", "cool", [])
