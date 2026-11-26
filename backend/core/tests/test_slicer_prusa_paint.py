"""PrusaSlicer 2.9.7 support and fuzzy execution contracts."""
from unittest import TestCase

from core.slicer_prusa_paint import audit_prusa_support_enforcer_gcode
from core.slicer_prusa_process_settings import enable_prusa_painted_support
from core.slicer_prusa_native_resolution import parse_prusa_profile


class PrusaPaintExecutionTests(TestCase):
    def test_native_process_enables_support_without_changing_automatic_choice(self):
        raw = b"layer_height = 0.2\nsupport_material = 0\nsupport_material_auto = 1\n"
        edited = enable_prusa_painted_support(raw)
        self.assertEqual(raw.splitlines()[1], b"support_material = 0")
        parsed = parse_prusa_profile(edited, "process")
        self.assertEqual(parsed["support_material"], "1")
        self.assertEqual(parsed["support_material_auto"], "1")
        defaulted = parse_prusa_profile(
            enable_prusa_painted_support(b"layer_height = 0.2\n"), "process")
        self.assertEqual(defaulted["support_material_auto"], "0")

    def test_support_role_audit_requires_actual_positive_xy_extrusion(self):
        data = (b";TYPE:Support material\nM82\nG92 X0 Y0 E0\n"
                b"G1 X1 Y2 E.125\nG1 X2 Y2 E.50\n"
                b";TYPE:Perimeter\nG1 X3 E.75\n")
        result = audit_prusa_support_enforcer_gcode(data)
        self.assertEqual(result["support_extrusion_moves"], 2)
        self.assertGreater(result["support_extrusion_e_mm"], .49)
        with self.assertRaisesRegex(ValueError, "no native support paths"):
            audit_prusa_support_enforcer_gcode(
                b";TYPE:Perimeter\nG1 X1 E1\n")
        with self.assertRaisesRegex(ValueError, "no native support paths"):
            audit_prusa_support_enforcer_gcode(
                b";TYPE:Support material\nG1 X1 E-.5\nG1 X2 E-.4\n")

    def test_support_role_audit_counts_relative_e_and_relative_xy(self):
        data = (b"G90\\nG0 X10 Y10\\nM83\\n"
                b";TYPE:Support material interface\\n"
                b"G91\\nG1 X1 Y0 E.04\\nG1 X0 Y1 E.05\\n"
                b"G90\\nG0 X40 Y40\\n;TYPE:External perimeter\\n"
                b"G1 X41 Y40 E.4\\n")
        result = audit_prusa_support_enforcer_gcode(data)
        self.assertEqual(result["support_extrusion_moves"], 2)
        self.assertEqual(result["support_extrusion_e_mm"], .09)

    def test_support_role_audit_rejects_stationary_priming(self):
        data = (b"G90\\nM82\\nG92 X0 Y0 E0\\n"
                b";TYPE:Support material\\n"
                b"G1 E.25\\nG1 E.5\\n"
                b";TYPE:Perimeter\\nG1 X1 Y0 E.6\\n")
        with self.assertRaisesRegex(ValueError, "no native support paths"):
            audit_prusa_support_enforcer_gcode(data)

    def test_support_role_audit_rejects_non_support_role(self):
        data = (b"G90\\nM82\\nG92 X0 Y0 E0\\n"
                b";TYPE:Unsupported perimeter\\n"
                b"G1 X1 Y0 E.2\\nG1 X2 Y0 E.4\\n")
        with self.assertRaisesRegex(ValueError, "no native support paths"):
            audit_prusa_support_enforcer_gcode(data)

    def test_support_role_audit_honours_g92_extruder_reset(self):
        data = (b"G90\\nM82\\nG92 X0 Y0 E40\\n"
                b";TYPE:Support material\\n"
                b"G1 X1 Y0 E40.03\\nG92 E0\\nG1 X2 Y0 E.04\\n")
        result = audit_prusa_support_enforcer_gcode(data)
        self.assertEqual(result["support_extrusion_moves"], 2)
        self.assertEqual(result["support_extrusion_e_mm"], .07)
