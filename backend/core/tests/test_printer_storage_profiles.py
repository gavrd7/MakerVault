"""Storage strategy contracts: never invent printer filesystem paths."""
from django.test import SimpleTestCase

from core.printer_storage_profiles import storage_profile


class PrinterStorageProfileTests(SimpleTestCase):
    def test_known_native_creality_roots(self):
        for model in ("Creality K1", "K1 Max", "K1C", "K1 SE"):
            with self.subTest(model=model):
                result = storage_profile("creality_local", model)
                self.assertEqual(result["path"], "/usr/data/printer_data/gcodes/")
                self.assertEqual(result["strategy"], "native_path")
        for model in ("Creality K2", "K2 Plus", "K2 Pro", "K2 SE"):
            with self.subTest(model=model):
                result = storage_profile("creality_local", model)
                self.assertEqual(result["path"], "/mnt/UDISK/printer_data/gcodes/")

    def test_unverified_creality_families_do_not_inherit_k2_root(self):
        for model in ("Creality Hi", "SPARKX i7", "SPARKX i8", "Ender-3 V3", "Ender-3 V3 KE", "Ender-3 V3 SE", "Mystery Model"):
            with self.subTest(model=model):
                result = storage_profile("creality_local", model)
                self.assertIsNone(result["path"])
                self.assertNotEqual(result["strategy"], "native_path")

    def test_vendor_api_paths_are_not_fabricated(self):
        cases = [
            ("bambu_local", "Bambu X1C", "ftps_model_profile"),
            ("bambu_local", "Bambu P1S", "ftps_model_profile"),
            ("bambu_local", "Bambu A1 Mini", "ftps_model_profile"),
            ("bambu_local", "Bambu H2D", "ftps_model_profile"),
            ("prusa", "Prusa MK4S", "prusalink_storage_api"),
            ("prusa", "Prusa CORE One", "prusalink_storage_api"),
            ("anycubic", "Kobra 3", "anycubic_upload_api"),
            ("flashforge", "FlashForge Adventurer 5M", "flashforge_model_api"),
            ("snapmaker", "Snapmaker U1", "moonraker_storage_api"),
            ("moonraker", "Custom Voron", "moonraker_storage_api"),
            ("octoprint", "Generic printer", "octoprint_storage_api"),
        ]
        for adapter, model, expected in cases:
            with self.subTest(model=model):
                result = storage_profile(adapter, model)
                self.assertEqual(result["strategy"], expected)
                self.assertIsNone(result["path"])

    def test_bambu_reference_routes_are_not_activated_for_upload(self):
        expected = [
            ("Bambu X1C", "/cache/", "gcode_file"),
            ("Bambu P1S", "/cache/", "gcode_file"),
            ("Bambu A1 Mini", "/cache/", "gcode_file"),
            ("Bambu A1", "/", "project_file"),
            ("Bambu P2S", "/cache/", "project_file"),
            ("Bambu H2D", "/", "project_file"),
        ]
        for model, directory, command in expected:
            with self.subTest(model=model):
                profile = storage_profile("bambu_local", model)
                self.assertEqual(profile["reference_route"]["remote_directory_hint"], directory)
                self.assertEqual(profile["reference_route"]["start_command_hint"], command)
                self.assertFalse(profile["reference_route"]["usable_for_upload"])
        self.assertIsNone(storage_profile("bambu_local", "Bambu X2D")["reference_route"])

    def test_unknown_model_and_adapter_never_get_generic_linux_root(self):
        for adapter in ("creality_local", "bambu_local", "prusa", "flashforge", "anycubic"):
            with self.subTest(adapter=adapter):
                result = storage_profile(adapter, "Unverified New Printer")
                self.assertEqual(result["strategy"], "unsupported_until_verified")
                self.assertIsNone(result["path"])
