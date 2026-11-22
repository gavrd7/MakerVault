"""Initial Bambu Studio offline CLI contract tests (no executable required)."""
import io
import json
import stat
import struct
import zipfile
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch, MagicMock

from slicer_worker.bambu_runner import bambu_command, extract_single_bambu_gcode, run_bambu
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

    def test_native_multifilament_3mf_uses_ordered_cli_palette(self):
        from slicer_worker.probe import fixture_bambu_core_3mf
        (self.root / "input.stl").unlink()
        (self.root / "input.3mf").write_bytes(fixture_bambu_core_3mf())
        for index in range(2):
            source = self.root / ("filament-" + str(index) + ".json")
            source.write_text(json.dumps({
                "type": "filament", "name": "Fixture PLA " + str(index),
                "filament_type": ["PLA"], "filament_diameter": ["1.75"],
            }))
        (self.root / "filament.json").write_bytes(
            (self.root / "filament-0.json").read_bytes())
        argv = bambu_command(self.binary, self.root)
        self.assertNotIn("--arrange", argv)
        self.assertEqual(argv[argv.index("--load-filaments") + 1],
                         str(self.root / "filament-0.json") + ";" +
                         str(self.root / "filament-1.json"))
        self.assertTrue(argv[-1].endswith("input.3mf"))

    def test_multifilament_refuses_missing_palette_member_and_mismatched_tool_zero(self):
        from slicer_worker.probe import fixture_bambu_core_3mf
        (self.root / "input.stl").unlink()
        (self.root / "input.3mf").write_bytes(fixture_bambu_core_3mf())
        (self.root / "filament-0.json").write_bytes(
            (self.root / "filament.json").read_bytes())
        (self.root / "filament-2.json").write_bytes(
            (self.root / "filament.json").read_bytes())
        with self.assertRaisesRegex(WorkerError, "contiguous"):
            bambu_command(self.binary, self.root)
        (self.root / "filament-2.json").rename(self.root / "filament-1.json")
        (self.root / "filament-0.json").write_text('{"type":"filament","name":"other"}')
        with self.assertRaisesRegex(WorkerError, "first native palette"):
            bambu_command(self.binary, self.root)
        (self.root / "filament-0.json").write_bytes(
            (self.root / "filament.json").read_bytes())
        (self.root / "filament-1.json").write_text(
            '{"type":"filament","name":"other","post_processing_scripts":"curl"}')
        with self.assertRaises(WorkerError):
            bambu_command(self.binary, self.root)

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

    def test_rejects_unexpected_secondary_gcode_member(self):
        # A future upstream layout must be re-reviewed rather than allowing
        # a valid plate to mask a second unsupported toolpath.
        for extra in ("Metadata/plate_0.gcode",
                      "Metadata/plate_2.GCODE",
                      "Metadata/subfolder/plate_2.gcode"):
            with self.subTest(extra=extra):
                self._archive([
                    ("Metadata/plate_1.gcode", b"G1 X2 E0.2\\n"),
                    (extra, b"G1 X3 E0.4\\n"),
                ])
                with self.assertRaisesRegex(WorkerError, "unexpected G-code"):
                    extract_single_bambu_gcode(
                        self.root / "bambu-sliced.3mf", self.root)
                self.assertFalse((self.root / "output.gcode").exists())

    def test_rejects_zip_member_exceeding_gcode_limit(self):
        from slicer_worker.runner import MAX_GCODE_BYTES
        self._archive([("Metadata/plate_1.gcode", b"G1 E1\n")])
        with zipfile.ZipFile(self.root / "bambu-sliced.3mf") as zf:
            self.assertEqual(len(zf.namelist()), 1)
        self.assertGreater(MAX_GCODE_BYTES, 1024)
        self.assertFalse((self.root / "output.gcode").exists())

    def test_duplicate_zip_members_are_rejected(self):
        import warnings
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", UserWarning)
            self._archive([
                ("Metadata/plate_1.gcode", b"G1 E1\\n"),
                ("Metadata/plate_1.gcode", b"G1 E2\\n"),
            ])
        with self.assertRaisesRegex(WorkerError, "duplicate"):
            extract_single_bambu_gcode(self.root / "bambu-sliced.3mf", self.root)
        self.assertFalse((self.root / "output.gcode").exists())

    def test_candidate_runner_writes_no_untrusted_stdout_and_accepts_one_plate(self):
        process = MagicMock()
        process.returncode = 0
        # The CLI must create output after validation, not before launch.
        process.communicate.side_effect = lambda **kwargs: self._archive([
            ("Metadata/plate_1.gcode", b"; test\\nG28\\n")])
        with patch("slicer_worker.bambu_runner.subprocess.Popen", return_value=process) as popen:
            result = run_bambu(self.binary, self.root)
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["bytes"], len(b"; test\\nG28\\n"))
        self.assertEqual(popen.call_args.kwargs["stdout"], __import__("subprocess").DEVNULL)
        self.assertEqual(popen.call_args.kwargs["stderr"], __import__("subprocess").DEVNULL)
        self.assertTrue(popen.call_args.kwargs["start_new_session"])
        env = popen.call_args.kwargs["env"]
        self.assertEqual(env["QT_QPA_PLATFORM"], "offscreen")
        self.assertEqual(env["SSL_CERT_FILE"], "/etc/ssl/certs/ca-certificates.crt")
        self.assertEqual(env["HOME"], str(self.root))
        self.assertNotIn("HTTP_PROXY", env)


    def test_candidate_runner_rejects_failed_cli_and_invalid_timeout(self):
        process = MagicMock()
        process.returncode = 42
        with patch("slicer_worker.bambu_runner.subprocess.Popen", return_value=process):
            with self.assertRaisesRegex(WorkerError, "rejected"):
                run_bambu(self.binary, self.root)
        for timeout in (0, 901, True, "30"):
            with self.subTest(timeout=timeout):
                with self.assertRaisesRegex(WorkerError, "timeout"):
                    run_bambu(self.binary, self.root, timeout_seconds=timeout)

    def test_bambu_runner_uses_standard_worker_admission(self):
        from slicer_worker.engine_registry import SUPPORTED
        from slicer_worker.service import _decode_payload
        import base64
        import uuid
        self.assertIn("bambustudio", SUPPORTED)
        payload = {
            "job_id": str(uuid.uuid4()), "engine": "bambustudio",
            "engine_version": "02.09.01.70",
            "model": base64.b64encode(fixture_stl()).decode(),
            "printer_profile": base64.b64encode(b"{}").decode(),
            "filament_profile": base64.b64encode(b"{}").decode(),
            "process_profile": base64.b64encode(b"{}").decode(),
        }
        decoded = _decode_payload(payload)
        self.assertEqual(decoded["model_format"], "stl")
