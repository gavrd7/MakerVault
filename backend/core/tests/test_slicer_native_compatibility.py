"""Known engine-native incompatibilities are diagnosed without changing presets."""
import json
from unittest import TestCase

from core.slicer_native_compatibility import (
    SlicerNativeCompatibilityError, check_native_compatibility,
)


class OrcaNativeCompatibilityTests(TestCase):
    def check(self, value, engine="orcaslicer", version="2.4.2", kind="printer"):
        raw = json.dumps({"retraction_distances_when_cut": value}).encode()
        return check_native_compatibility(engine, version, kind, raw)

    def test_official_k2_value_is_explained_not_clamped(self):
        raw = b'{"retraction_distances_when_cut":"30"}'
        with self.assertRaisesRegex(SlicerNativeCompatibilityError, r"30.*10.18"):
            check_native_compatibility("orcaslicer", "2.4.2", "printer", raw)
        self.assertEqual(json.loads(raw)["retraction_distances_when_cut"], "30")

    def test_other_manufacturer_profiles_are_checked_identically(self):
        for printer in ("Generic Cartesian 300", "Voron 2.4", "Prusa MK4", "Custom CoreXY"):
            with self.subTest(printer=printer):
                raw = json.dumps({
                    "name": printer,
                    "retraction_distances_when_cut": "30",
                }).encode()
                with self.assertRaisesRegex(SlicerNativeCompatibilityError, "regardless of printer"):
                    check_native_compatibility("orcaslicer", "2.4.2", "printer", raw)

    def test_boundary_values_and_missing_key_are_allowed(self):
        for value in ("10", "18", ["10", "18"]):
            with self.subTest(value=value):
                self.check(value)
        check_native_compatibility("orcaslicer", "2.4.2", "printer", b'{"name":"other"}')

    def test_other_engine_version_or_kind_not_changed(self):
        self.check("30", version="2.4.3")
        self.check("30", engine="crealityprint")
        self.check("30", kind="filament")

    def test_other_invalid_known_numeric_values_rejected(self):
        for value in (0, 9.99, 18.01, 30, ["18", "30"]):
            with self.subTest(value=value), self.assertRaises(SlicerNativeCompatibilityError):
                self.check(value)
