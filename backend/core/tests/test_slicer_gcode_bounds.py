"""Native multi-material G-code bounds: prevent off-bed prime tower extrusion."""
from django.test import SimpleTestCase

from core.slicer_gcode_bounds import (
    GcodeExtrusionBoundsError, audit_extrusion_xy_bounds,
)


class CrealityOutputBoundsTests(SimpleTestCase):
    def test_inside_bed_absolute_and_relative_moves(self):
        gcode = """
G90
M82
G1 X10 Y10 F12000
G1 X20 Y20 E1
G92 E0
M83
G91
G1 X10 Y10 E0.4
G90
G1 X250 Y250 E0.5
"""
        result = audit_extrusion_xy_bounds(gcode, width=260, depth=260)
        self.assertEqual(result["extrusion_moves_checked"], 3)

    def test_out_of_bed_tower_is_rejected(self):
        gcode = """
G90
M83
G1 X30 Y30
G1 X40 Y40 E1.0
G1 X280 Y30
G1 X290 Y30 E0.8 ; prime tower outside 260-mm bed
"""
        with self.assertRaisesRegex(
                GcodeExtrusionBoundsError, "outside the native printable"):
            audit_extrusion_xy_bounds(gcode, width=260, depth=260)

    def test_outside_travel_without_extrusion_is_not_tower(self):
        # Position is outside but never extrudes until inside again.
        gcode = "G90\nM83\nG0 X300 Y300\nG0 X20 Y20\nG1 X30 Y30 E1\n"
        self.assertEqual(
            audit_extrusion_xy_bounds(gcode, width=260, depth=260)["extrusion_moves_checked"], 1)

    def test_no_xy_extrusion_fails_closed(self):
        with self.assertRaisesRegex(GcodeExtrusionBoundsError, "No bounded"):
            audit_extrusion_xy_bounds("G90\nG1 X20 Y20\n", width=260, depth=260)
