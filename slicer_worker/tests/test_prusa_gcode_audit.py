"""Security and positive-material evidence for the Prusa-only native G-code gate."""
from unittest import TestCase
from pathlib import Path
from tempfile import TemporaryDirectory

from slicer_worker.prusa_gcode_audit import (audit_prusa_positive_e,
    run_prusa_painted_with_numeric_recheck)
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

    def test_extruder_position_survives_mode_switch(self):
        # Relative E+1 repeated 25 times reaches E=25. Switching to M82
        # and commanding E=20 is retraction, not a new positive extrusion.
        prefix = b"; harmless header\n" * 200 + b"M83\nG92 E0\n"
        deposits = b"".join(
            f"G1 X{i+40} Y50 E1\n".encode() for i in range(25)
        )
        tail = b"M82\nG1 X85 Y50 E20\n"
        result = audit_prusa_positive_e(prefix + deposits + tail)
        self.assertEqual(result["positive_e_moves"], 25)

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


    def test_painted_mmu_numeric_overflow_retry_discards_corrupt_output(self):
        invalid = self.gcode().replace(b"Y50", b"Y99999999999999")
        valid = self.gcode()
        with TemporaryDirectory() as temporary:
            folder = Path(temporary)
            attempts = []
            def runner(_binary, workdir, *, timeout_seconds):
                self.assertEqual(workdir, folder)
                self.assertEqual(timeout_seconds, 20)
                self.assertFalse((folder / "output.gcode").exists())
                payload = invalid if not attempts else valid
                attempts.append(payload)
                (folder / "output.gcode").write_bytes(payload)
                return {"bytes": len(payload)}
            receipt, gcode = run_prusa_painted_with_numeric_recheck(
                runner, Path("native"), folder, timeout_seconds=20,
                max_bytes=1024*1024)
            self.assertEqual(receipt["bytes"], len(valid))
            self.assertEqual(gcode, valid)
            self.assertEqual(len(attempts), 2)
            self.assertEqual(audit_prusa_positive_e(gcode)["positive_e_moves"], 32)

    def test_repeated_native_numeric_overflow_fails_closed_after_three_attempts(self):
        bad = self.gcode().replace(b"Y50", b"Y99999999999999")
        with TemporaryDirectory() as temporary:
            folder = Path(temporary)
            count = 0
            def runner(_binary, workdir, *, timeout_seconds):
                nonlocal count
                count += 1
                self.assertFalse((folder / "output.gcode").exists())
                (folder / "output.gcode").write_bytes(bad)
                return {"bytes": len(bad)}
            with self.assertRaisesRegex(WorkerError, "invalid coordinates"):
                run_prusa_painted_with_numeric_recheck(
                    runner, Path("native"), folder, timeout_seconds=20,
                    max_bytes=1024*1024)
            self.assertEqual(count, 3)

    def test_painted_mmu_does_not_retry_other_unsafe_gcode(self):
        for invalid in (self.gcode()+b"\x00", self.gcode()[:100],
                        self.gcode() + b"\xff"):
            with self.subTest(case=len(invalid)):
                with TemporaryDirectory() as temporary:
                    folder=Path(temporary)
                    attempts=[]
                    def runner(_binary, workdir, *, timeout_seconds):
                        attempts.append(True)
                        (folder / "output.gcode").write_bytes(invalid)
                        return {"bytes":len(invalid)}
                    with self.assertRaises(WorkerError):
                        run_prusa_painted_with_numeric_recheck(
                            runner, Path("native"), folder,
                            timeout_seconds=20, max_bytes=1024*1024)
                    self.assertEqual(len(attempts),1)

    def test_painted_mmu_never_retries_oversized_native_output(self):
        with TemporaryDirectory() as temporary:
            folder=Path(temporary)
            count=0
            def runner(_binary, workdir, *, timeout_seconds):
                nonlocal count
                count+=1
                (folder / "output.gcode").write_bytes(self.gcode())
                return {"bytes": len(self.gcode())}
            with self.assertRaisesRegex(WorkerError, "size limit"):
                run_prusa_painted_with_numeric_recheck(
                    runner, Path("native"), folder,
                    timeout_seconds=20, max_bytes=2000)
            self.assertEqual(count,1)
