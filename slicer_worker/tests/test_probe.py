import os
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch

from slicer_worker.probe import fixture_stl, run_probe, _validate_gcode
from slicer_worker.runner import WorkerError
from slicer_worker.stl_validation import validate_stl


class RealEngineProbeTests(TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.binary = self.root / "verified-engine"
        self.binary.write_bytes(b"offline unit test executable")
        self.binary.chmod(0o700)
        for kind in ("printer", "filament", "process"):
            (self.root / (kind + ".json")).write_text('{"name":"Unit fixture"}')

    def kwargs(self):
        return {
            "engine": "crealityprint", "version": "7.3.0",
            "binary": str(self.binary),
            "printer": str(self.root / "printer.json"),
            "filament": str(self.root / "filament.json"),
            "process": str(self.root / "process.json"),
        }

    def test_binary_fixture_passes_structural_stl_validation(self):
        result = validate_stl(fixture_stl())
        self.assertEqual(result["format"], "binary")

    def test_real_runner_path_and_extrusion_are_required(self):
        def fake_runner(binary, root, *, timeout_seconds):
            self.assertEqual(binary, self.binary)
            self.assertEqual(timeout_seconds, 120)
            self.assertTrue((root / "input.stl").is_file())
            (root / "output.gcode").write_bytes(
                b"; offline unit fixture\nG1 X1.2 Y2.1 E0.4 F1200\n")
            return {"status": "completed"}
        with patch("slicer_worker.probe.ENGINES", {"crealityprint": fake_runner}):
            result = run_probe(**self.kwargs())
        self.assertEqual(result["status"], "passed")
        self.assertEqual(result["engine"], "crealityprint")
        self.assertEqual(len(result["binary_sha256"]), 64)
        self.assertEqual(set(result["profile_sha256"]), {"printer", "filament", "process"})

    def test_empty_and_comment_only_outputs_fail_closed(self):
        for gcode in (b"", b"; no extrusion\n" * 10):
            with self.subTest(gcode=gcode):
                output = self.root / "output.gcode"
                output.write_bytes(gcode)
                with self.assertRaises(WorkerError):
                    _validate_gcode(output)

    def test_no_unapproved_or_symlink_binary(self):
        with self.assertRaises(WorkerError):
            run_probe(**{**self.kwargs(), "engine": "unsupported"})
        link = self.root / "engine-link"
        link.symlink_to(self.binary)
        with self.assertRaisesRegex(WorkerError, "symlinked"):
            run_probe(**{**self.kwargs(), "binary": str(link)})

    def test_runner_failure_does_not_fabricate_receipt(self):
        def failure(binary, root, *, timeout_seconds):
            raise WorkerError("Native engine could not slice the fixture.")
        with patch("slicer_worker.probe.ENGINES", {"crealityprint": failure}):
            with self.assertRaisesRegex(WorkerError, "could not slice"):
                run_probe(**self.kwargs())
