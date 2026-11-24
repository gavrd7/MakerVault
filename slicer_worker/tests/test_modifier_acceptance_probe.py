"""Offline G-code audit must only count positive-E planar model deposition."""
import unittest

from slicer_worker.modifier_acceptance_probe import regional_extrusion


class ModifierRealAuditTests(unittest.TestCase):
    def test_relative_e_and_absolute_e_resets_exclude_travel_and_retractions(self):
        gcode = b"\n".join([
            b"G90", b"M83", b"G1 X100 Y100 Z5", b"G1 X110 Y110 E1.0",
            b"G1 X111 Y111 E-0.5", b"G0 X200 Y200",
            b"G1 X210 Y210 E50", b"G0 X100 Y100",
            b"G1 Z14", b"M82", b"G92 E0", b"G1 X110 Y110 E2",
            b"G1 X111 Y111 E1.5", b"G1 X112 Y112 E3.0",
        ])
        result = regional_extrusion(gcode)
        self.assertEqual(result["moves"], {"control": 1, "changed": 2})
        self.assertAlmostEqual(result["totals"]["control"], 1.0)
        self.assertAlmostEqual(result["totals"]["changed"], 3.5)

    def test_no_extrusion_outside_model_area_or_layer_bands(self):
        result = regional_extrusion(b"\n".join([
            b"G90", b"M83", b"G1 X1 Y1 Z5", b"G1 X2 Y2 E10",
            b"G1 X100 Y100 Z25", b"G1 X110 Y110 E10",
        ]))
        self.assertEqual(result["moves"], {"control": 0, "changed": 0})


if __name__ == "__main__":
    unittest.main()
