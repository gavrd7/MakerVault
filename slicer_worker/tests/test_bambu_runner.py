"""Initial Bambu Studio offline CLI contract tests (no executable required)."""
import io
import json
import stat
import struct
import zipfile
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase

from slicer_worker.bambu_runner import bambu_command, extract_single_bambu_gcode
from slicer_worker.runner import WorkerError


def fixture_stl():
    return b"MakerVault fixture".ljust(80, b" ") + struct.pack(
        "<I", 1) + struct.pack(
        "<12fH", 0, 0, 1, 0, 0, 0, 10, 0, 0, 0, 10, 0, 0)


class BambuRunnerContractTests(TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.binary = self.root / "bambu-studio"
        self.binary.write_text("fixture executable")
        self.binary.chmod(0o700)
        (self.root / "input.stl").write_bytes(fixture_stl())
        for part in ("printer", "process", "filament"):
            (self.root / (part + ".json")).write_text(
                json.dumps({"type": part, "name": "Fixture " + part}))

    def test_documented_flags_are_fixed_and_paths_are_sandbox_local(self):
        argv = bambu_command(self.binary, self.root)
        self.assertIn("--load-settings", argv)
        self.assertIn("--load-filaments", argv)
        self.assertIn("--export-3mf", argv)
        self.assertIn("--arrange", argv)
        self.assertEqual(argv[argv.index("--slice") + 1], "0")
        self.assertTrue(argv[-1].endswith("input.stl"))

    def test_staged_native_profile_must_not_inherit_or_postprocess(self):
        profile = self.root / "printer.json"
        profile.write_text(json.dumps({"inherits": "unknown"}))
        with self.assertRaises(WorkerError):
            bambu_command(self.binary, self.root)
        profile.write_text(json.dumps({"post_process": "run arbitrary commands"}))
        with self.assertRaises(WorkerError):
            bambu_command(self.binary, self.root)

    def test_network_preferences_scrubbed_only_in_scratch_profile(self):
        profile = self.root / "printer.json"
        profile.write_text(json.dumps({
            "name": "Fixture printer", "print_host": "192.0.2.1",
            "machine_start_gcode": "G28",
        }))
        bambu_command(self.binary, self.root)
        value = json.loads(profile.read_text())
        self.assertNotIn("print_host", value)
        self.assertEqual(value["machine_start_gcode"], "G28")

    def _archive(self, items):
        with zipfile.ZipFile(self.root / "bambu-sliced.3mf", "w") as zf:
            for name, data in items:
                zf.writestr(name, data)

    def test_extracts_single_plain_text_plate_without_unzipping_other_entries(self):
        self._archive([
            ("Metadata/plate_1.gcode", b"; Bambu Studio\nG28\nG1 X2 E0.2\n"),
            ("Metadata/credentials.txt", b"should never be extracted"),
        ])
        out = extract_single_bambu_gcode(
            self.root / "bambu-sliced.3mf", self.root)
        self.assertEqual(out.name, "output.gcode")
        self.assertIn(b"G28", out.read_bytes())
        self.assertFalse((self.root / "Metadata").exists())

    def test_rejects_multiplate_missing_plate_or_binary_data(self):
        for items in (
            [("Metadata/plate_1.gcode", b"G1 E1\n"),
             ("Metadata/plate_2.gcode", b"G1 E2\n")],
            [("3D/3dmodel.model", b"<model/>")],
            [("Metadata/plate_1.gcode", b"\0binary")],
        ):
            with self.subTest(items=items):
                self._archive(items)
                with self.assertRaises(WorkerError):
                    extract_single_bambu_gcode(
                        self.root / "bambu-sliced.3mf", self.root)

    def test_rejects_zip_member_exceeding_gcode_limit(self):
        from slicer_worker.runner import MAX_GCODE_BYTES
        self._archive([("Metadata/plate_1.gcode", b"G1 E1\n")])
        with zipfile.ZipFile(self.root / "bambu-sliced.3mf") as zf:
            self.assertEqual(len(zf.namelist()), 1)
        self.assertGreater(MAX_GCODE_BYTES, 1024)
        self.assertFalse((self.root / "output.gcode").exists())
