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
        data = (b";TYPE:Support material\nM82\nG92 E0\n"
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
