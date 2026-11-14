import json
from unittest import TestCase

from slicer_worker.k2_cfs_acceptance import k2_offline_profile_evidence
from slicer_worker.runner import WorkerError


class K2OfflineProfileAcceptanceTests(TestCase):
    def setUp(self):
        self.printer = {
            "name": "Creality K2 0.4 nozzle",
            "single_extruder_multi_material": "1",
            "manual_filament_change": "0",
            "purge_in_prime_tower": "1",
            "change_filament_gcode": "G1 X0 Y140 F3000",
        }
        self.process = {
            "enable_prime_tower": "1",
            "flush_volumes_matrix": ["0", "300", "220", "0"],
        }

    def check(self, printer=None, process=None):
        return k2_offline_profile_evidence(
            json.dumps(self.printer if printer is None else printer).encode(),
            json.dumps(self.process if process is None else process).encode())

    def test_offline_acceptance_does_not_approve_physical_cfs(self):
        result = self.check()
        self.assertTrue(result["k2_native_profile_checked"])
        self.assertEqual(result["directional_flush_mm3"], [300, 220])
        self.assertFalse(result["physical_cfs_approved"])

    def test_wrong_machine_or_manual_changer_fails_closed(self):
        for replacement in (
            {"name": "Creality K1 0.4 nozzle"},
            {"name": "Creality K2 Plus 0.4 nozzle"},
            {"single_extruder_multi_material": "0"},
            {"manual_filament_change": "1"},
            {"purge_in_prime_tower": "0"},
            {"change_filament_gcode": ""},
        ):
            with self.subTest(replacement=replacement):
                with self.assertRaises(WorkerError):
                    self.check(printer={**self.printer, **replacement})

    def test_missing_or_malformed_flushing_fails_closed(self):
        for replacement in (
            {"enable_prime_tower": "0"},
            {"flush_volumes_matrix": ["0", "300", "0"]},
            {"flush_volumes_matrix": ["0", "0", "300", "0"]},
            {"flush_volumes_matrix": ["0", "inf", "220", "0"]},
            {"flush_volumes_matrix": ["0", "300", "NaN", "0"]},
        ):
            with self.subTest(replacement=replacement):
                with self.assertRaises(WorkerError):
                    self.check(process={**self.process, **replacement})
