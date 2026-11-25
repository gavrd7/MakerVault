"""PrusaSlicer 2.9.7 support and fuzzy execution contracts."""
from types import SimpleNamespace
from unittest import TestCase

from core.slicer_prusa_paint import audit_prusa_support_enforcer_gcode
from core.slicer_prusa_process_settings import enable_prusa_painted_support
from core.slicer_prusa_native_resolution import parse_prusa_profile
from core.slicer_execution import _validate_plate_execution, SlicerExecutionError


class PrusaPaintExecutionTests(TestCase):
    def _job(self, painted):
        row = {"asset_id": "owned-cube", "x_mm": 0, "y_mm": 0,
               "z_mm": 0, "rotation_deg": 0, "scale_percent": 100,
               **painted}
        return SimpleNamespace(engine="prusaslicer", engine_version="2.9.7",
                               settings={"plate_objects": [row]},
                               owner=None, printer_profile_id="native-printer")

    @staticmethod
    def _paint(slot=0):
        return {"version": 2, "signature": "12:deadbeef",
                "regions": [{"slot": slot, "patches": [{
                    "face": 0, "polygon": [[0,0,0],[1,0,0],[0,1,0]]}]}]}

    def test_native_enforcer_blocker_and_fuzzy_admitted_separately(self):
        for row in (
            {"support_paint": self._paint(0)},
            {"support_paint": self._paint(1)},
            {"fuzzy_skin_paint": self._paint(0)},
        ):
            with self.subTest(row=row):
                self.assertTrue(_validate_plate_execution(self._job(row)))

    def test_mixed_modes_and_unqualified_seams_stay_blocked(self):
        for row in (
            {"support_paint": self._paint(0), "fuzzy_skin_paint": self._paint(0)},
            {"support_paint": self._paint(0),
             "process_overrides": {"wall_loops": 4}},
            {"fuzzy_skin_paint": self._paint(0),
             "modifier_volumes": [{"kind": "negative"}]},
            {"seam_paint": self._paint(0)},
        ):
            with self.subTest(row=row), self.assertRaises(SlicerExecutionError):
                _validate_plate_execution(self._job(row))

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
