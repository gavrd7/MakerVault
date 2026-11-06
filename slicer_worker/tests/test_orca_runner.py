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
        (self.root / "input.stl").write_bytes(b"sample-model")
        for name in ("printer.json", "filament.json", "process.json"):
            (self.root / name).write_text('{"name":"Native preset"}')

    def test_fixed_orca_cli_uses_native_json_profiles(self):
        cmd = orca_command(self.binary, self.root)
        self.assertEqual(cmd[0], str(self.binary))
        self.assertEqual(cmd[1], str(self.root / "input.stl"))
        self.assertEqual(cmd[cmd.index("--slice") + 1], "1")
        self.assertEqual(cmd[cmd.index("--load-filaments") + 1], str(self.root / "filament.json"))
        self.assertIn(str(self.root / "printer.json") + ";" + str(self.root / "process.json"), cmd)

    def test_forbids_postprocessing_and_network_settings(self):
        for field in ("post_process_scripts", "printhost_apikey", "print_host"):
            (self.root / "printer.json").write_text('{"' + field + '":"unsafe"}')
            with self.subTest(field=field), self.assertRaises(WorkerError):
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
