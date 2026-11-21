from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch

from slicer_worker.verify_orca import verify_fixture
from slicer_worker.runner import WorkerError


class OrcaFixtureVerificationTests(TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.binary = self.root / "orca"
        self.binary.write_bytes(b"#! /bin/sh\nexit 0\n")
        self.binary.chmod(0o700)
        self.files = {}
        for name, content in (
            ("model", b"solid test\nendsolid test\n"),
            ("printer", b'{"name":"test printer"}'),
            ("filament", b'{"name":"test filament"}'),
            ("process", b'{"name":"test process"}'),
        ):
            path = self.root / (name + (".stl" if name == "model" else ".json"))
            path.write_bytes(content)
            self.files[name] = path

    def verify(self):
        return verify_fixture(self.binary, **self.files)

    def test_real_cli_receipt_is_not_automatically_approved(self):
        def run_side_effect(binary, scratch):
            path = scratch / "output.gcode"
            path.write_bytes(b"; fixture output\nG1 X10 Y20 E1\n")
            return {"status": "completed", "gcode_path": str(path), "bytes": path.stat().st_size}
        with patch("slicer_worker.verify_orca.run_orca", side_effect=run_side_effect):
            report = self.verify()
        self.assertFalse(report["approved_for_production"])
        self.assertEqual(report["gcode_bytes"], len(b"; fixture output\nG1 X10 Y20 E1\n"))
        self.assertEqual(len(report["gcode_sha256"]), 64)
        self.assertEqual(report["engine_binary_sha256"], __import__("hashlib").sha256(self.binary.read_bytes()).hexdigest())
        self.assertFalse(report["approved_for_production"])

    def test_rejects_empty_or_unsafe_output(self):
        for generated in (b"", b"; no path\n", b"M112\nG1 X1 Y1\n", b"G1 X1 Y1\x00"):
            def run_side_effect(binary, scratch):
                path = scratch / "output.gcode"
                path.write_bytes(generated)
                return {"status": "completed", "gcode_path": str(path), "bytes": len(generated)}
            with self.subTest(generated=generated), patch(
                "slicer_worker.verify_orca.run_orca", side_effect=run_side_effect
            ), self.assertRaises(WorkerError):
                self.verify()

    def test_rejects_symlink_fixture_inputs(self):
        fake = self.root / "link.json"
        fake.symlink_to(self.files["printer"])
        self.files["printer"] = fake
        with self.assertRaises(WorkerError):
            self.verify()
