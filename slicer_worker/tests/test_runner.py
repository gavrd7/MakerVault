"""No slicer binary is needed to validate the worker command contract."""
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch
import os

from slicer_worker.runner import WorkerError, prusa_command, run_prusa
from scripts.prusa_real_binary_smoke import cube_stl


class WorkerContractTests(TestCase):
    def setUp(self):
        self.scratch = TemporaryDirectory()
        self.addCleanup(self.scratch.cleanup)
        self.root = Path(self.scratch.name)
        self.executable = self.root / "prusa-slicer"
        self.executable.write_text("#!/bin/sh\nexit 0\n")
        self.executable.chmod(0o700)
        (self.root / "input.stl").write_bytes(cube_stl())
        (self.root / "printer.ini").write_text(
            "printer_technology = FFF\nnozzle_diameter = 0.4\n"
            "bed_shape = 0x0,200x0,200x200,0x200\n")
        (self.root / "filament.ini").write_text(
            "filament_diameter = 1.75\ntemperature = 210\n")
        (self.root / "process.ini").write_text(
            "layer_height = 0.2\nfill_density = 15%\n")
        self.output = self.root / "output.gcode"

    def test_fixed_command_never_takes_user_command_parameters(self):
        args = prusa_command(self.executable, self.root)
        self.assertEqual(args[0], str(self.executable))
        self.assertEqual(args[-1], str(self.root / "input.stl"))
        self.assertIn("--export-gcode", args)
        self.assertEqual(args.count("--load"), 3)

    def test_symlink_input_and_existing_output_are_rejected(self):
        (self.root / "printer.ini").unlink()
        (self.root / "printer.ini").symlink_to(self.root / "filament.ini")
        with self.assertRaises(WorkerError):
            prusa_command(self.executable, self.root)
        (self.root / "printer.ini").unlink()
        (self.root / "printer.ini").write_text(
            "printer_technology = FFF\nnozzle_diameter = 0.4\n"
            "bed_shape = 0x0,200x0,200x200,0x200\n")
        self.output.write_text("old output")
        with self.assertRaises(WorkerError):
            prusa_command(self.executable, self.root)

    def test_mocked_completed_job_validates_output(self):
        self.output.write_text("; generated\nG1 X1 Y2 E1\n")
        # An output cannot exist before execution; let our mocked process
        # produce it as a side effect.
        self.output.unlink()
        class FakeProcess:
            pid = 100
            returncode = 0
            def communicate(inner, timeout=None):
                self.output.write_text("; generated\nG1 X1 Y2 E1\n")
                return b"", b""
        with patch("slicer_worker.runner.subprocess.Popen", return_value=FakeProcess()) as popen:
            result = run_prusa(self.executable, self.root)
        self.assertEqual(result["status"], "completed")
        self.assertTrue(result["bytes"] > 10)
        args = popen.call_args
        self.assertTrue(args.kwargs["start_new_session"])
        self.assertNotIn("SHELL", args.kwargs["env"])

    def test_process_failure_never_returns_raw_engine_output(self):
        class FakeProcess:
            pid = 101
            returncode = 7
            def communicate(self, timeout=None):
                return b"secret-preset", b"private-key"
        with patch("slicer_worker.runner.subprocess.Popen", return_value=FakeProcess()):
            with self.assertRaises(WorkerError) as failure:
                run_prusa(self.executable, self.root)
        self.assertNotIn("secret", str(failure.exception))
        self.assertNotIn("private", str(failure.exception))

    def test_post_processing_scripts_are_rejected(self):
        (self.root / "printer.ini").write_text("post_process = /tmp/untrusted.sh\\n")
        with self.assertRaisesRegex(WorkerError, "Post-processing"):
            prusa_command(self.executable, self.root)

    def test_actual_nul_in_native_profile_is_rejected(self):
        # A literal backslash-x-zero-zero sequence is not a binary NUL.
        (self.root / "printer.ini").write_bytes(b"layer_height = 0.2\n\x00")
        with self.assertRaisesRegex(WorkerError, "binary"):
            prusa_command(self.executable, self.root)

    def test_plain_escaped_text_is_not_a_binary_nul(self):
        (self.root / "printer.ini").write_bytes(
            b"; a literal \\x00 sequence\nprinter_technology = FFF\n"
            b"nozzle_diameter = 0.4\nbed_shape = 0x0,200x0,200x200,0x200\n")
        self.assertIn("--export-gcode", prusa_command(self.executable, self.root))

    def test_malformed_stl_is_rejected_before_engine_launch(self):
        (self.root / "input.stl").write_bytes(b"not an STL")
        with self.assertRaisesRegex(WorkerError, "STL"):
            prusa_command(self.executable, self.root)

    def test_invalid_timeout_and_oversize_models_fail_without_execution(self):
        with self.assertRaises(WorkerError):
            run_prusa(self.executable, self.root, timeout_seconds=0)
        (self.root / "input.stl").write_bytes(b"")
        with self.assertRaises(WorkerError):
            prusa_command(self.executable, self.root)
