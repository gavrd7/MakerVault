import json
from django.test import SimpleTestCase
from core.slicer_native_overrides import apply_orca_job_overrides, ORCA_PLATES


class NativeSlicerPlateAndColourTests(SimpleTestCase):
    def test_selected_plate_changes_only_job_settings(self):
        process = json.dumps({"name": "K2 0.20", "layer_height": "0.2"}).encode()
        filament = json.dumps({
            "name": "PLA", "cool_plate_temp": ["50"],
            "textured_plate_temp": ["65"],
            "default_filament_colour": ["#F2754E"],
        }).encode()
        for plate_type, native_name in ORCA_PLATES.items():
            with self.subTest(plate_type=plate_type):
                p, f = apply_orca_job_overrides(process, filament, plate_type, [])
                result = json.loads(p)
                if native_name is None:
                    self.assertNotIn("curr_bed_type", result)
                else:
                    self.assertEqual(result["curr_bed_type"], native_name)
                self.assertEqual(json.loads(f)["cool_plate_temp"], ["50"])
                self.assertEqual(json.loads(f)["textured_plate_temp"], ["65"])
        self.assertNotIn("curr_bed_type", json.loads(process))

    def test_single_model_selected_white_is_sent_to_native_filament(self):
        process = b'{"name":"Standard"}'
        filament = b'{"default_filament_colour":["#F2754E"]}'
        p, f = apply_orca_job_overrides(process, filament, "textured_pei", [
            {"asset_id": "1", "color": "#ffffff"},
        ])
        self.assertEqual(json.loads(p)["curr_bed_type"], "Textured PEI Plate")
        self.assertEqual(json.loads(p)["filament_colour"], ["#FFFFFF"])
        self.assertEqual(json.loads(f)["default_filament_colour"], ["#FFFFFF"])

    def test_multiple_colours_do_not_invent_multimaterial_mappings(self):
        p, f = apply_orca_job_overrides(
            b'{"name":"Standard"}',
            b'{"default_filament_colour":["#F2754E"]}', "default",
            [{"color": "#FFFFFF"}, {"color": "#000000"}],
        )
        self.assertNotIn("filament_colour", json.loads(p))
        self.assertEqual(json.loads(f)["default_filament_colour"], ["#F2754E"])

    def test_rejects_unknown_plate_and_malformed_profiles(self):
        with self.assertRaisesRegex(ValueError, "plate"):
            apply_orca_job_overrides(b"{}", b"{}", "unknown", [])
        with self.assertRaises(ValueError):
            apply_orca_job_overrides(b"[]", b"{}", "cool", [])
