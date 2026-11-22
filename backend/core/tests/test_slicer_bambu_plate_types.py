"""Bambu shares the native build-plate picker and validated temperature vector."""
import json
from types import SimpleNamespace
from unittest.mock import patch
from django.test import SimpleTestCase
from core.slicer_plate_types import inspect_engine_plates, apply_creality_plate


class BambuNativePlateTests(SimpleTestCase):
    def profile(self):
        return SimpleNamespace(engine="bambustudio", kind="printer")

    @patch("core.slicer_plate_types.resolved_native_profile")
    def test_native_machine_plates_use_same_options_as_creality(self, resolve):
        resolve.return_value = json.dumps({
            "type": "machine", "name": "Bambu X1C 0.4 nozzle",
            "printable_area": ["0x0", "256x0", "256x256", "0x256"],
            "not_support_bed_types": ["Engineering Plate"],
        }).encode()
        row = inspect_engine_plates(self.profile())
        self.assertIn("textured_pei", row["supported"])
        self.assertNotIn("engineering", row["supported"])
        self.assertIsNone(row["default"])

    @patch("core.slicer_plate_types.resolved_native_profile")
    def test_selected_plate_updates_only_job_process_copy(self, resolve):
        resolve.return_value = b'{"type":"machine","name":"Bambu X1C 0.4 nozzle"}'
        process = b'{"type":"process","name":"0.20mm Standard"}'
        filament = b'{"type":"filament","name":"PLA","textured_plate_temp":["55"],"textured_plate_temp_initial_layer":["60"]}'
        modified_process, modified_filament = apply_creality_plate(
            process, filament, "textured_pei", self.profile())
        self.assertEqual(json.loads(modified_process)["curr_bed_type"], "Textured PEI Plate")
        self.assertEqual(modified_filament, filament)
        self.assertNotIn(b"curr_bed_type", process)
        unchanged_process, unchanged_filament = apply_creality_plate(
            process, filament, "default", self.profile())
        self.assertEqual(json.loads(unchanged_process)["name"], "0.20mm Standard")
        self.assertEqual(unchanged_filament, filament)
