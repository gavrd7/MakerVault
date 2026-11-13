from django.test import SimpleTestCase

from core.slicer_material_gcode_audit import (
    MaterialGcodeAuditError, audit_native_tool_usage,
)


class NativeToolEvidenceTests(SimpleTestCase):
    def test_requires_both_tool_selections_and_extrusion(self):
        gcode = """; T9 is a comment, not a selection
M83
T0
G1 X10 E0.5 F1200
G1 E-0.2
T1
G1 X20 E0.7 F1200
T0
G1 X30 E0.1
"""
        result = audit_native_tool_usage(gcode, expected_tools={0, 1})
        self.assertEqual(result["selection_sequence"], (0, 1, 0))
        self.assertEqual(result["extruding_moves"], {0: 2, 1: 1})

    def test_single_colour_gcode_cannot_pass_multi_colour_verification(self):
        gcode = "T0\nM83\nG1 X10 E1\n; T1\n"
        with self.assertRaisesRegex(MaterialGcodeAuditError, "omitted a required tool"):
            audit_native_tool_usage(gcode, expected_tools={0, 1})

    def test_tool_selection_without_extrusion_does_not_pass(self):
        with self.assertRaisesRegex(MaterialGcodeAuditError, "omitted extrusion"):
            audit_native_tool_usage("T0\nM83\nG1 X10 E1\nT1\nG1 X20 F600\n",
                                    expected_tools={0, 1})

    def test_absolute_e_and_g92_are_handled_per_tool(self):
        gcode = ("M82\nT0\nG92 E0\nG1 X10 E1\n"
                 "T1\nG92 E0\nG1 X20 E2\nG92 E0\nG1 X30 E1\n")
        result = audit_native_tool_usage(gcode, expected_tools=[0, 1])
        self.assertEqual(result["extruding_moves"], {0: 1, 1: 2})

    def test_invalid_fixture_rejected(self):
        for expected in ({0}, {0, True}, {0, 16}):
            with self.subTest(expected=expected):
                with self.assertRaises(MaterialGcodeAuditError):
                    audit_native_tool_usage("T0\nT1\n", expected_tools=expected)
