import json
from types import SimpleNamespace
from unittest.mock import patch
from django.test import SimpleTestCase
from core.slicer_bed_dimensions import trusted_plate_dimensions
from core.slicer_profiles import SlicerProfileError


class NativeBedDimensionsTests(SimpleTestCase):
    @patch("core.slicer_bed_dimensions.resolved_native_profile")
    def test_creality_k1_k2_from_own_native_presets(self, resolved):
        printer = SimpleNamespace(engine="crealityprint", kind="printer")
        for area, expected in [
            ("0x0,220x0,220x220,0x220", (220.0, 220.0)),
            ("0x0,260x0,260x260,0x260", (260.0, 260.0)),
        ]:
            with self.subTest(area=area):
                resolved.return_value = json.dumps({"printable_area": area}).encode()
                self.assertEqual(trusted_plate_dimensions(printer), expected)

    @patch("core.slicer_bed_dimensions.resolved_native_profile")
    def test_orca_same_coordinates_but_different_native_representation(self, resolved):
        printer = SimpleNamespace(engine="orcaslicer", kind="printer")
        resolved.return_value = json.dumps({
            "printable_area": ["0x0", "220x0", "220x220", "0x220"],
        }).encode()
        self.assertEqual(trusted_plate_dimensions(printer), (220, 220))

    @patch("core.slicer_bed_dimensions.resolved_native_profile")
    def test_orca_k2_inherited_empty_exclusion_list(self, resolved):
        printer = SimpleNamespace(engine="orcaslicer", kind="printer")
        for exclusion in (["0x0"], "0x0", [], None):
            with self.subTest(exclusion=exclusion):
                resolved.return_value = json.dumps({
                    "printable_area": ["0x0", "260x0", "260x260", "0x260"],
                    "printable_height": "260",
                    "bed_exclude_area": exclusion,
                }).encode()
                self.assertEqual(trusted_plate_dimensions(printer), (260.0, 260.0))

    @patch("core.slicer_bed_dimensions.resolved_native_profile")
    def test_orca_real_exclusion_list_remains_blocked(self, resolved):
        printer = SimpleNamespace(engine="orcaslicer", kind="printer")
        resolved.return_value = json.dumps({
            "printable_area": ["0x0", "260x0", "260x260", "0x260"],
            "bed_exclude_area": ["0x0", "40x40"],
        }).encode()
        with self.assertRaisesRegex(SlicerProfileError, "exclusion"):
            trusted_plate_dimensions(printer)

    @patch("core.slicer_bed_dimensions.resolved_native_profile")
    def test_exclusion_and_shifted_beds_fail_closed(self, resolved):
        printer = SimpleNamespace(engine="crealityprint", kind="printer")
        for geometry in [
            {"printable_area": "-110x-110,110x-110,110x110,-110x110"},
            {"printable_area": "0x0,220x0,220x220,0x220", "bed_exclude_area": "0x10,10x10"},
            {"printable_area": "0x0,220x0,110x220,0x220"},
        ]:
            with self.subTest(geometry=geometry):
                resolved.return_value = json.dumps(geometry).encode()
                with self.assertRaises(SlicerProfileError):
                    trusted_plate_dimensions(printer)
