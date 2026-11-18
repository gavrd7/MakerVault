"""Creality CLI contract tests do not need an installed Creality binary."""
import json
import struct
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch

from slicer_worker.creality_runner import creality_command, run_creality, _cli_failure_reason
from slicer_worker.runner import WorkerError


def one_triangle_stl():
    return b"MakerVault fixture".ljust(80, b" ") + struct.pack("<I", 1) + struct.pack(
        "<12fH", 0, 0, 1, 0, 0, 0, 10, 0, 0, 0, 10, 0, 0
    )


class CrealityCommandTests(TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.binary = self.root / "creality-print"
        self.binary.write_bytes(b"test fixture")
        self.binary.chmod(0o700)
        (self.root / "input.stl").write_bytes(one_triangle_stl())
        for kind in ("printer", "filament", "process"):
            (self.root / (kind + ".json")).write_text(json.dumps({"name": kind}))

    def test_uses_creality_native_flags_not_orca_flags(self):
        cmd = creality_command(self.binary, self.root)
        self.assertIn("--load_settings", cmd)
        self.assertIn("--load_filaments", cmd)
        self.assertNotIn("--load-settings", cmd)
        self.assertNotIn("--load-filaments", cmd)
        self.assertEqual(cmd[-1], str(self.root / "input.stl"))

    def test_unsafe_profile_and_inherited_parent_rejected(self):
        (self.root / "process.json").write_text(json.dumps({"post_process": "touch /tmp/unsafe"}))
        with self.assertRaises(WorkerError):
            creality_command(self.binary, self.root)
        (self.root / "process.json").write_text(json.dumps({"inherits": "unbundled-parent"}))
        with self.assertRaises(WorkerError):
            creality_command(self.binary, self.root)

    def test_network_preferences_removed_only_from_temporary_creality_profile(self):
        path = self.root / "printer.json"
        original = {
            "name": "K2", "print_host": "192.0.2.5",
            "printhost_apikey": "not-a-real-token",
            "machine_start_gcode": "G28",
        }
        path.write_text(json.dumps(original))
        cmd = creality_command(self.binary, self.root)
        cleaned = json.loads(path.read_text())
        self.assertNotIn("print_host", cleaned)
        self.assertNotIn("printhost_apikey", cleaned)
        self.assertEqual(cleaned["machine_start_gcode"], "G28")
        self.assertIn("--cli", cmd)
        # The initial source payload remains unchanged in memory.
        self.assertEqual(original["print_host"], "192.0.2.5")

    def test_post_processing_commands_still_rejected(self):
        path = self.root / "printer.json"
        path.write_text(json.dumps({
            "print_host": "192.0.2.5",
            "post_process_scripts": ["touch /tmp/unsafe"],
        }))
        with self.assertRaisesRegex(WorkerError, "blocked post-processing"):
            creality_command(self.binary, self.root)

    def test_cli_diagnostics_are_safe_categories_only(self):
        self.assertEqual(
            _cli_failure_reason(b"qt.qpa.plugin: Could not load the Qt platform plugin"),
            "Creality Print CLI could not initialise its headless Qt platform.")
        self.assertEqual(
            _cli_failure_reason(b"error while loading shared libraries: libXYZ.so"),
            "Creality Print CLI is missing a runtime library.")
        self.assertEqual(
            _cli_failure_reason(b"failed to load settings from secret/private/location"),
            "Creality Print CLI could not load a native preset.")
        self.assertEqual(
            _cli_failure_reason(b"unexpected details with /private/location and token=test"),
            "Creality Print failed to slice using the selected native profiles.")

    def test_creality_cli_parser_diagnostics_are_classified(self):
        self.assertEqual(
            _cli_failure_reason(b"error: Only one CLI command may be specified"),
            "Creality Print CLI received conflicting commands.")
        self.assertEqual(
            _cli_failure_reason(b"error: No CLI command was specified"),
            "Creality Print CLI did not recognise a slicing command.")
        self.assertEqual(
            _cli_failure_reason(b"CLI parameter parsing failed"),
            "Creality Print CLI rejected its command-line parameters.")

    def test_linux_254_is_reported_as_invalid_cli_parameters(self):
        class FakeProcess:
            pid = 123
            returncode = 254
            def communicate(self, timeout=None):
                return None, None
        with patch("slicer_worker.creality_runner.subprocess.Popen",
                   return_value=FakeProcess()):
            with self.assertRaisesRegex(
                WorkerError, "command-line parameters"
            ):
                run_creality(self.binary, self.root)

    def test_real_output_required_before_declaring_success(self):
        class FakeProcess:
            pid = 123
            returncode = 0
            def communicate(self, timeout=None):
                return b"", b""
        with patch("slicer_worker.creality_runner.subprocess.Popen", return_value=FakeProcess()):
            with self.assertRaisesRegex(WorkerError, "output directory"):
                run_creality(self.binary, self.root)

    def test_fixed_success_receipt_for_mock_subprocess(self):
        root = self.root
        class FakeProcess:
            pid = 123
            returncode = 0
            def communicate(self, timeout=None):
                out = root / "creality-output"
                out.mkdir()
                (out / "output.gcode").write_bytes(b"; generated test only\nG1 X1 Y2 E1\n")
                return b"", b""
        with patch("slicer_worker.creality_runner.subprocess.Popen", return_value=FakeProcess()) as spawn:
            result = run_creality(self.binary, self.root)
        self.assertEqual(result["status"], "completed")
        self.assertGreater(result["bytes"], 10)
        self.assertTrue(spawn.call_args.kwargs["start_new_session"])
        self.assertNotIn("SHELL", spawn.call_args.kwargs["env"])
