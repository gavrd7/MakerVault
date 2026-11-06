from types import SimpleNamespace
from unittest.mock import patch

from django.test import SimpleTestCase
from core.slicer_bed import inspect_orca_plate


class OrcaPlateInspectionTests(SimpleTestCase):
    def setUp(self):
        self.printer = SimpleNamespace(engine="orcaslicer", kind="printer")

    def inspect(self, json_obj):
        with patch("core.slicer_bed._inspect_source", return_value=json_obj):
            return inspect_orca_plate(self.printer)

    def test_bed_bounds_from_native_polygon(self):
        result = self.inspect({
            "printable_area": ["0x0", "220x0", "220x220", "0x220"],
            "printable_height": "250",
        })
        self.assertEqual(result["status"], "available")
        self.assertEqual(result["size_mm"], [220, 220, 250])
        self.assertEqual(result["fit_check"], "not_performed")

    def test_parent_profiles_are_not_silently_resolved(self):
        result = self.inspect({"inherits": "Creality K1 base", "printable_area": ["0x0", "220x0", "220x220"]})
        self.assertEqual(result["status"], "requires_parent")

    def test_child_machine_with_explicit_bed_dimensions_is_partial_not_approved(self):
        result = self.inspect({
            "inherits": "fdm_creality_common",
            "printable_area": ["0x0", "260x0", "260x260", "0x260"],
            "printable_height": "260",
        })
        self.assertEqual(result["status"], "partial")
        self.assertEqual(result["size_mm"], [260, 260, 260])
        self.assertEqual(result["parent"], "fdm_creality_common")
        self.assertEqual(result["fit_check"], "not_performed")

    def test_incomplete_and_invalid_profiles_do_not_claim_fit(self):
        for obj in (
            {}, {"printable_area": ["0x0", "220x0", "220x220"]},
            {"printable_area": ["0x0", "bad", "0x220"], "printable_height": "220"},
            {"printable_area": ["0x0", "220x0", "0x220"], "printable_height": "NaN"},
            {"printable_area": ["0x0", "0x0", "0x0"], "printable_height": "200"},
        ):
            with self.subTest(obj=obj):
                self.assertNotEqual(self.inspect(obj)["status"], "available")
