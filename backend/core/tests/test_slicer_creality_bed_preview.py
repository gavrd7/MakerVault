from types import SimpleNamespace
from unittest.mock import patch

from django.test import SimpleTestCase

from core.slicer_bed import inspect_creality_plate
from core.slicer_profiles import SlicerProfileError


class CrealityNativeBedPreviewTests(SimpleTestCase):
    @patch("core.slicer_bed._inspect_source")
    def test_k1_and_k2_native_dimensions_are_displayed(self, inspect):
        printer = SimpleNamespace(engine="crealityprint", kind="printer")
        for width, height in ((220, 250), (260, 260)):
            with self.subTest(width=width):
                inspect.return_value = {
                    "inherits": "fdm_creality_common",
                    "printable_area": f"0x0,{width}x0,{width}x{width},0x{width}",
                    "printable_height": str(height),
                }
                plate = inspect_creality_plate(printer)
                self.assertEqual(plate["size_mm"], [width, width, height])
                self.assertEqual(plate["status"], "partial")
                self.assertEqual(plate["fit_check"], "not_performed")

    @patch("core.slicer_bed._inspect_source")
    def test_missing_inherited_dimensions_are_not_invented(self, inspect):
        inspect.return_value = {"inherits": "fdm_creality_common"}
        printer = SimpleNamespace(engine="crealityprint", kind="printer")
        self.assertEqual(inspect_creality_plate(printer)["status"], "requires_parent")

    @patch("core.slicer_bed._inspect_source")
    def test_invalid_or_skewed_creality_bed_is_not_rendered(self, inspect):
        printer = SimpleNamespace(engine="crealityprint", kind="printer")
        inspect.return_value = {
            "printable_area": "0x0,260x0,125x260,0x260",
            "printable_height": "260",
        }
        self.assertEqual(inspect_creality_plate(printer)["status"], "invalid")
        with self.assertRaises(SlicerProfileError):
            inspect_creality_plate(SimpleNamespace(engine="orcaslicer", kind="printer"))
