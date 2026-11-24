"""Security and positive-material evidence for the Prusa-only native G-code gate."""
from unittest import TestCase

from slicer_worker.prusa_gcode_audit import audit_prusa_positive_e
from slicer_worker.runner import WorkerError


class PrusaGcodeAuditTests(TestCase):
    def gcode(self, *, relative=False):
        start = "; PrusaSlicer generated native G-code\n" + ("M83\n" if relative else "M82\n")
        start += "G92 E0\n"
        start += "; setup\n" * 300
        moves = ["G1 Z0.2 F600"]
        for i in range(32):
            value = 0.6 if relative else (i + 1) * 0.6
            moves.append(f"G1 X{i+50} Y50 E{value:.3f} F1200")
        return (start + "\n".join(moves) + "\n").encode()

    def test_genuine_planar_extrusion_in_absolute_and_relative_modes(self):
        for relative in (True, False):
            with self.subTest(relative=relative):
                result = audit_prusa_positive_e(self.gcode(relative=relative))
                self.assertEqual(result["positive_e_moves"], 32)

    def test_reset_and_retraction_cannot_fake_positive_material(self):
        data = b"; padding\n" * 300 + b"M82\nG92 E0\n"
        data += b"G1 E10 F2400\nG1 X30 Y40 E10\n" * 25
        with self.assertRaisesRegex(WorkerError, "insufficient"):
            audit_prusa_positive_e(data)

    def test_refuse_binary_malformed_and_empty_gcode(self):
        for data in (
            b"",
            b"; empty\n" * 400,
            self.gcode() + b"\x00",
            self.gcode() + b"\xff",
            self.gcode().replace(b"E0.600", b"E1e999"),
        ):
            with self.subTest(size=len(data)):
                with self.assertRaises(WorkerError):
                    audit_prusa_positive_e(data)

    def test_no_gcode_data_or_script_reaches_error_message(self):
        payload = self.gcode() + b"\0private-preset-marker"
        with self.assertRaises(WorkerError) as ctx:
            audit_prusa_positive_e(payload)
        self.assertNotIn("private-preset-marker", str(ctx.exception))
