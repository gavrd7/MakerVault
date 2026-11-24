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

    def test_single_nozzle_dual_variant_is_resolved_only_with_explicit_type(self):
        from slicer_worker.bambu_runner import _select_single_nozzle_cli_variant
        for volume, expected in (
            ("Standard", "Direct Drive Standard"),
            (["High Flow"], "Direct Drive High Flow"),
        ):
            with self.subTest(volume=volume):
                machine = self.root / "printer.json"
                machine.write_text(json.dumps({
                    "type": "machine", "name": "BBL single-nozzle fixture",
                    "nozzle_diameter": ["0.4"],
                    "nozzle_volume_type": volume,
                    "extruder_variant_list":
                        ["Direct Drive Standard,Direct Drive High Flow"],
                    "printer_extruder_variant":
                        ["Direct Drive Standard,Direct Drive High Flow"],
                    "machine_start_gcode": "G28",
                }))
                self.assertTrue(_select_single_nozzle_cli_variant(machine))
                updated = json.loads(machine.read_text())
                self.assertEqual(updated["extruder_variant_list"], [expected])
                self.assertEqual(updated["printer_extruder_variant"], [expected])
                self.assertEqual(updated["nozzle_diameter"], ["0.4"])
                self.assertEqual(updated["machine_start_gcode"], "G28")

    def test_ambiguous_or_multi_nozzle_variant_is_never_changed(self):
        from slicer_worker.bambu_runner import _select_single_nozzle_cli_variant
        base = {
            "type": "machine", "name": "BBL fixture",
            "nozzle_diameter": ["0.4"],
            "extruder_variant_list": [
                "Direct Drive Standard,Direct Drive High Flow"],
            "printer_extruder_variant": [
                "Direct Drive Standard,Direct Drive High Flow"],
        }
        for changes in (
            {},
            {"nozzle_volume_type": "Other"},
            {"nozzle_diameter": ["0.4", "0.4"], "nozzle_volume_type": "Standard"},
            {"extruder_variant_list": ["Unknown,Atypical"], "nozzle_volume_type": "Standard"},
            {"printer_extruder_variant": ["Unknown"], "nozzle_volume_type": "Standard"},
        ):
            with self.subTest(changes=changes):
                machine = self.root / "printer.json"
                profile = {**base, **changes}
                original = json.dumps(profile)
                machine.write_text(original)
                if not changes:
                    with self.assertLogs("slicer_worker.bambu_runner", level="WARNING"):
                        self.assertFalse(_select_single_nozzle_cli_variant(machine))
                else:
                    self.assertFalse(_select_single_nozzle_cli_variant(machine))
                self.assertEqual(machine.read_text(), original)

    def test_bambu_command_normalises_scratch_only_without_changing_other_profiles(self):
        machine = self.root / "printer.json"
        machine.write_text(json.dumps({
            "type": "machine", "name": "BBL single-nozzle fixture",
            "nozzle_diameter": ["0.4"], "nozzle_volume_type": "Standard",
            "extruder_variant_list": ["Direct Drive Standard,Direct Drive High Flow"],
            "printer_extruder_variant": ["Direct Drive Standard,Direct Drive High Flow"],
        }))
        original_filament = (self.root / "filament.json").read_bytes()
        original_process = (self.root / "process.json").read_bytes()
        args = bambu_command(self.binary, self.root)
        self.assertIn("--load-settings", args)
        self.assertEqual(
            json.loads(machine.read_text())["printer_extruder_variant"],
            ["Direct Drive Standard"])
        self.assertEqual((self.root / "filament.json").read_bytes(), original_filament)
        self.assertEqual((self.root / "process.json").read_bytes(), original_process)

    def test_bambu_runtime_xdg_directories_are_private_and_scratch_only(self):
        from slicer_worker.bambu_runner import _bambu_headless_environment
        env = _bambu_headless_environment(self.root)
        for key in ("XDG_CONFIG_HOME", "XDG_CACHE_HOME", "XDG_DATA_HOME", "XDG_RUNTIME_DIR"):
            directory = Path(env[key])
            self.assertEqual(directory.parent, self.root)
            self.assertTrue(directory.is_dir())
            self.assertEqual(directory.stat().st_mode & 0o777, 0o700)
        self.assertEqual(env["HOME"], str(self.root))
        self.assertEqual(env["TMPDIR"], str(self.root))
        self.assertNotIn("HTTP_PROXY", env)

    def test_bambu_filesystem_abort_diagnostics_never_relay_paths(self):
        from slicer_worker.bambu_runner import _filesystem_error_details
        self.assertEqual(_filesystem_error_details(
            b"boost::filesystem::filesystem_error: Permission denied: "
            b"/opt/engine-store/versions/bambustudio/private-data"),
            ("permission", "engine-store"))
        self.assertEqual(_filesystem_error_details(
            b"filesystem_error: No such file or directory: "
            b"/tmp/makervault-slice-private-secret/file"),
            ("missing-path", "worker-scratch"))
        self.assertEqual(_filesystem_error_details(b"filesystem_error"),
                         ("unknown", "unknown"))

    def test_documented_flags_are_fixed_and_paths_are_sandbox_local(self):
        argv = bambu_command(self.binary, self.root)
        self.assertIn("--load-settings", argv)
        self.assertIn("--load-filaments", argv)
        self.assertIn("--export-3mf", argv)
        self.assertIn("--arrange", argv)
        self.assertEqual(argv[argv.index("--slice") + 1], "0")
        self.assertTrue(argv[-1].endswith("input.stl"))

    def test_native_multifilament_3mf_uses_ordered_cli_palette(self):
        from scripts.probe_bambu_multicolour import make_bambu_material_fixture
        (self.root / "input.stl").unlink()
        (self.root / "input.3mf").write_bytes(make_bambu_material_fixture())
        for index in range(2):
            source = self.root / ("filament-" + str(index) + ".json")
            source.write_text(json.dumps({
                "type": "filament", "name": "MakerVault PLA Tool " + str(index + 1),
                "filament_type": ["PLA"], "filament_diameter": ["1.75"],
                "filament_id": "GFA00", "filament_is_support": ["0"],
                "filament_extruder_variant": [
                    "Direct Drive Standard", "Direct Drive High Flow"],
                "filament_flow_ratio": ["0.98", "0.98"],
                "nozzle_temperature": ["220", "220"],
                "nozzle_temperature_initial_layer": ["220", "220"],
                "filament_max_volumetric_speed": ["21", "29"],
                "filament_retraction_length": ["nil", "0.4"],
            }))
        (self.root / "filament.json").write_bytes(
            (self.root / "filament-0.json").read_bytes())
        argv = bambu_command(self.binary, self.root)
        self.assertNotIn("--arrange", argv)
        self.assertNotIn("--load-filaments", argv)
        self.assertIn("--load-settings", argv)
        self.assertTrue(argv[-1].endswith("input.3mf"))

    def test_native_project_rejects_a_tampered_selected_material(self):
        from scripts.probe_bambu_multicolour import make_bambu_material_fixture
        (self.root / "input.stl").unlink()
        (self.root / "input.3mf").write_bytes(make_bambu_material_fixture())
        for index in range(2):
            (self.root / ("filament-" + str(index) + ".json")).write_text(json.dumps({
                "type": "filament", "name": "MakerVault PLA Tool " + str(index + 1),
                "filament_type": ["PLA"], "filament_diameter": ["1.75"],
                "filament_id": "GFA00", "filament_is_support": ["0"],
                "filament_extruder_variant": [
                    "Direct Drive Standard", "Direct Drive High Flow"],
                "filament_flow_ratio": ["0.98", "0.98"],
                "nozzle_temperature": ["220", "220"],
                "nozzle_temperature_initial_layer": ["220", "220"],
                "filament_max_volumetric_speed": ["21", "29"],
                "filament_retraction_length": ["nil", "0.4"],
            }))
        (self.root / "filament.json").write_bytes(
            (self.root / "filament-0.json").read_bytes())
        bambu_command(self.binary, self.root)
        altered = json.loads((self.root / "filament-1.json").read_text())
        altered["nozzle_temperature"] = ["250", "250"]
        (self.root / "filament-1.json").write_text(json.dumps(altered))
        with self.assertRaisesRegex(WorkerError, "does not match"):
            bambu_command(self.binary, self.root)

    def test_multifilament_refuses_missing_palette_member_and_mismatched_tool_zero(self):
        from scripts.probe_bambu_multicolour import make_bambu_material_fixture
        (self.root / "input.stl").unlink()
        (self.root / "input.3mf").write_bytes(make_bambu_material_fixture())
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
        self.assertTrue(hasattr(popen.call_args.kwargs["stdout"], "fileno"))
        self.assertEqual(popen.call_args.kwargs["stderr"], __import__("subprocess").STDOUT)
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

    def test_sigabrt_reports_only_whitelisted_exception_type(self):
        process = MagicMock()
        process.returncode = -6
        with patch("slicer_worker.bambu_runner.subprocess.Popen",
                   return_value=process) as popen:
            def emit(**kwargs):
                popen.call_args.kwargs["stdout"].write(
                    b"terminate called after throwing an instance of "
                    b"'std::filesystem::filesystem_error'\\n"
                    b"what(): /private/sensitive-model-location\\n")
            process.communicate.side_effect = emit
            with self.assertLogs("slicer_worker.bambu_runner", level="WARNING") as logs:
                with self.assertRaisesRegex(WorkerError, "SIGABRT"):
                    run_bambu(self.binary, self.root)
        messages = "\\n".join(logs.output)
        self.assertIn("exception type: filesystem-error", messages)
        self.assertIn("SIGABRT classified: uncaught-exception", messages)
        self.assertNotIn("sensitive-model-location", messages)

    def test_sigabrt_reports_only_safe_exception_type(self):
        process = MagicMock()
        process.returncode = -6
        with patch("slicer_worker.bambu_runner.subprocess.Popen", return_value=process):
            with self.assertLogs("slicer_worker.bambu_runner", level="WARNING") as logs:
                with self.assertRaisesRegex(WorkerError, "SIGABRT"):
                    run_bambu(self.binary, self.root)
        self.assertTrue(any("SIGABRT classified: unclassified" in row for row in logs.output))
        self.assertTrue(any("exception type: unknown" in row for row in logs.output))

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
