import struct
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch

from slicer_worker.orca_runner import orca_command, run_orca
from slicer_worker.runner import WorkerError


class OrcaRunnerTests(TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.binary = self.root / "orca-slicer"
        self.binary.write_text("#!/bin/sh\nexit 0\n")
        self.binary.chmod(0o700)
        (self.root / "input.stl").write_bytes(
            b"STL fixture".ljust(80, b" ") + struct.pack("<I", 1)
            + struct.pack("<12fH", 0, 0, 1, 0, 0, 0, 10, 0, 0, 0, 10, 0, 0)
        )
        for name in ("printer.json", "filament.json", "process.json"):
            (self.root / name).write_text('{"name":"Native preset"}')

    def test_fixed_orca_cli_uses_native_json_profiles(self):
        cmd = orca_command(self.binary, self.root)
        self.assertEqual(cmd[0], str(self.binary))
        self.assertEqual(cmd[1], str(self.root / "input.stl"))
        self.assertEqual(cmd[cmd.index("--slice") + 1], "1")
        self.assertIn("--load-defaultfila", cmd)
        self.assertEqual(cmd[cmd.index("--mtcpp") + 1], "500000")
        self.assertEqual(cmd[cmd.index("--mstpp") + 1], "300")
        self.assertEqual(cmd[cmd.index("--load-filaments") + 1], str(self.root / "filament.json"))
        self.assertIn(str(self.root / "process.json") + ";" + str(self.root / "printer.json"), cmd)

    def test_rejects_fake_stl_before_launching_orca(self):
        (self.root / "input.stl").write_bytes(b"not a real STL")
        with self.assertRaisesRegex(WorkerError, "STL"):
            orca_command(self.binary, self.root)

    def test_rejects_postprocessing_commands(self):
        for field in ("post_process_scripts", "post_process", "post_processing_scripts"):
            (self.root / "printer.json").write_text('{"' + field + '":"unsafe"}')
            with self.subTest(field=field), self.assertRaisesRegex(WorkerError, "Unsafe"):
                orca_command(self.binary, self.root)

    def test_official_print_host_fields_are_removed_only_from_scratch(self):
        import json
        incoming = {
            "name": "Creality K1 (0.4 nozzle)", "nozzle_diameter": ["0.4"],
            "print_host": "192.0.2.1", "printhost_apikey": "not-sent",
            "printhost_authorization_type": "key",
            "settings": {"print_host_webui": "https://example.invalid"},
        }
        (self.root / "printer.json").write_text(json.dumps(incoming))
        cmd = orca_command(self.binary, self.root)
        self.assertIn("--slice", cmd)
        cleaned = json.loads((self.root / "printer.json").read_text())
        self.assertEqual(cleaned["name"], incoming["name"])
        self.assertEqual(cleaned["nozzle_diameter"], ["0.4"])
        self.assertNotIn("print_host", cleaned)
        self.assertNotIn("printhost_apikey", cleaned)
        self.assertNotIn("printhost_authorization_type", cleaned)
        self.assertNotIn("print_host_webui", cleaned["settings"])
        # Another profile without network fields is never rewritten.
        self.assertEqual((self.root / "filament.json").read_text(), '{"name":"Native preset"}')

    def test_nested_postprocessing_remains_blocked_even_with_host_keys(self):
        (self.root / "printer.json").write_text(
            '{"print_host":"192.0.2.1","nested":{"post_process_scripts":["curl bad"]}}'
        )
        with self.assertRaisesRegex(WorkerError, "Unsafe"):
            orca_command(self.binary, self.root)

    def test_inherited_profiles_are_not_sliced_without_parent_bundle(self):
        (self.root / "printer.json").write_text('{"name":"Printer child","inherits":"Vendor base"}')
        with self.assertRaisesRegex(WorkerError, "parent preset"):
            orca_command(self.binary, self.root)

    def test_successful_mock_orca_output_is_normalised(self):
        outdir = self.root / "orca-output"
        class FakeProcess:
            returncode = 0
            def communicate(inner, timeout=None):
                outdir.mkdir()
                (outdir / "plate_1.gcode").write_text("; sliced\nG1 X1 Y1 E0.1\n")
        with patch("slicer_worker.orca_runner.subprocess.Popen", return_value=FakeProcess()):
            result = run_orca(self.binary, self.root)
        self.assertTrue(Path(result["gcode_path"]).is_file())
        self.assertEqual(result["bytes"], len(b"; sliced\nG1 X1 Y1 E0.1\n"))

    def test_real_cli_result_json_does_not_invalidate_single_gcode(self):
        outdir = self.root / "orca-output"
        class FakeProcess:
            returncode = 0
            def communicate(inner, timeout=None):
                outdir.mkdir()
                (outdir / "plate_1.gcode").write_text("; sliced\\nG1 X1 Y1 E0.1\\n")
                (outdir / "result.json").write_text('{"succeed":true}')
                (outdir / "plate_1.statistics.json").write_text('{"time":23}')
        with patch("slicer_worker.orca_runner.subprocess.Popen", return_value=FakeProcess()):
            result = run_orca(self.binary, self.root)
        self.assertEqual(result["status"], "completed")
        self.assertEqual((self.root / "output.gcode").read_text(), "; sliced\\nG1 X1 Y1 E0.1\\n")

    def test_extra_output_and_symlinks_fail_closed(self):
        outdir = self.root / "orca-output"
        class FakeProcess:
            returncode = 0
            def communicate(inner, timeout=None):
                outdir.mkdir()
                (outdir / "plate_1.gcode").write_text("G1 X1 Y1")
                (outdir / "plate_2.gcode").write_text("G1 X2 Y2")
        with patch("slicer_worker.orca_runner.subprocess.Popen", return_value=FakeProcess()):
            with self.assertRaises(WorkerError):
                run_orca(self.binary, self.root)
