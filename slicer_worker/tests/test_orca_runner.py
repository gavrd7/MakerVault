import struct
import io
import zipfile
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch

from slicer_worker.orca_runner import orca_command, run_orca, _safe_out_of_range_options
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


    def test_ordered_native_multi_filament_cli_requires_explicit_3mf_tools(self):
        from unittest.mock import patch
        project = self.root / "input.3mf"
        with zipfile.ZipFile(project, "w") as package:
            package.writestr("3D/3dmodel.model", "<model/>")
            package.writestr("Metadata/model_settings.config",
                '<config><object id="1"><metadata key="extruder" value="1"/></object>'
                '<object id="2"><metadata key="extruder" value="2"/></object></config>')
        (self.root / "filament-0.json").write_text('{"name":"Native preset"}')
        (self.root / "filament-1.json").write_text('{"name":"Second"}')
        with patch("slicer_worker.orca_runner.validate_worker_3mf") as validate:
            command = orca_command(self.binary, self.root)
        self.assertEqual(command[command.index("--load-filaments") + 1],
                         str(self.root / "filament-0.json") + ";" +
                         str(self.root / "filament-1.json"))
        self.assertEqual(command[command.index("--arrange") + 1], "0")
        self.assertTrue(any(call.kwargs.get("native_tool_count") == 2
                            for call in validate.call_args_list))

    def test_native_multi_filament_cli_rejects_missing_intermediate_profile(self):
        with zipfile.ZipFile(self.root / "input.3mf", "w") as package:
            package.writestr("3D/3dmodel.model", "<model/>")
            package.writestr("Metadata/model_settings.config",
                '<config><object id="1"><metadata key="extruder" value="1"/></object>'
                '<object id="2"><metadata key="extruder" value="2"/></object></config>')
        (self.root / "filament-0.json").write_text('{"name":"Native preset"}')
        (self.root / "filament-2.json").write_text('{"name":"Third"}')
        with patch("slicer_worker.orca_runner.validate_worker_3mf"):
            with self.assertRaisesRegex(WorkerError, "Non-contiguous"):
                orca_command(self.binary, self.root)

    def test_experimental_native_plate_modes_are_probe_only(self):
        with self.assertRaisesRegex(WorkerError, "requires a 3MF input"):
            orca_command(self.binary, self.root, experimental_all_plates=True)
        with self.assertRaisesRegex(WorkerError, "requires a 3MF input"):
            orca_command(self.binary, self.root, experimental_no_arrange=True)
        package = io.BytesIO()
        with zipfile.ZipFile(package, "w") as archive:
            archive.writestr("3D/3dmodel.model", "<model/>")
            archive.writestr("Metadata/model_settings.config", 
                             '<config><object id="1"><metadata key="wall_loops" value="5"/></object></config>')
        (self.root / "input.3mf").write_bytes(package.getvalue())
        with patch("slicer_worker.orca_runner.validate_worker_3mf"):
            regular = orca_command(self.binary, self.root)
            self.assertEqual(regular[regular.index("--slice") + 1], "1")
            self.assertEqual(regular[regular.index("--arrange") + 1], "0")
            diagnostic = orca_command(self.binary, self.root,
                                      experimental_all_plates=True,
                                      experimental_no_arrange=True)
        self.assertEqual(diagnostic[diagnostic.index("--slice") + 1], "0")
        self.assertEqual(diagnostic[diagnostic.index("--arrange") + 1], "0")

    def test_generic_3mf_without_per_object_metadata_keeps_existing_cli(self):
        package = io.BytesIO()
        with zipfile.ZipFile(package, "w") as archive:
            archive.writestr("3D/3dmodel.model", "<model/>")
        (self.root / "input.3mf").write_bytes(package.getvalue())
        with patch("slicer_worker.orca_runner.validate_worker_3mf"):
            command = orca_command(self.binary, self.root)
        self.assertNotIn("--arrange", command)
        self.assertEqual(command[command.index("--slice") + 1], "1")

    def test_verified_appimage_uses_pre_extracted_entrypoint(self):
        original = self.root / "orcaslicer.AppImage"
        original.write_bytes(b"official pinned AppImage fixture")
        original.chmod(0o700)
        appdir = self.root / "squashfs-root"
        appdir.mkdir()
        entry = appdir / "AppRun"
        entry.write_text("#!/bin/sh\\nexit 0\\n")
        entry.chmod(0o700)
        command = orca_command(original, self.root)
        self.assertEqual(command[0], str(entry))
        self.assertEqual(command[1], str(self.root / "input.stl"))

    def test_unextracted_appimage_fails_without_ever_invoking_fuse(self):
        original = self.root / "orcaslicer.AppImage"
        original.write_bytes(b"official pinned AppImage fixture")
        original.chmod(0o700)
        with self.assertRaisesRegex(WorkerError, "no extracted runtime"):
            orca_command(original, self.root)

    def test_extracted_entrypoint_cannot_escape_pinned_directory(self):
        original = self.root / "orcaslicer.AppImage"
        original.write_bytes(b"official pinned AppImage fixture")
        original.chmod(0o700)
        appdir = self.root / "squashfs-root"
        appdir.mkdir()
        (appdir / "AppRun").symlink_to(self.binary)
        with self.assertRaisesRegex(WorkerError, "unsafe"):
            orca_command(original, self.root)

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

    def test_orca_cli_failure_category_is_safe_and_specific(self):
        import io
        class FakeProcess:
            returncode = 1
            stderr = io.BytesIO(b"qt.qpa.plugin: Could not load the Qt platform plugin xcb in /private/path")
            def wait(self, timeout=None):
                return self.returncode
        with patch("slicer_worker.orca_runner.subprocess.Popen", return_value=FakeProcess()):
            with self.assertRaisesRegex(WorkerError, "qt-platform-failed"):
                run_orca(self.binary, self.root)

    def test_out_of_range_diagnostic_only_reports_known_setting_names(self):
        output = (b"Param values in 3mf/config error:\n"
                  b"wall_filament: 0 not in range [1.0,100.0]\n"
                  b"tree_support_wall_count: -1 not in range [0.0,2.0]\n"
                  b"api_key: 123 not in range [0,999]\n"
                  b"/private/path to user file\n")
        self.assertEqual(_safe_out_of_range_options(output),
                         ("wall_filament", "tree_support_wall_count"))
        self.assertEqual(_safe_out_of_range_options(b"Nothing to report"), ())

    def test_settings_error_is_retained_when_worker_output_is_verbose(self):
        import io
        from slicer_worker.orca_runner import _bounded_stderr
        from collections import deque
        first, last = deque(), deque()
        payload = (b"Param values in 3mf/config error:\n"
                   b"new_supported_setting: 0 not in range [1, 20]\n"
                   + b"verbose output\n" * 2000)
        _bounded_stderr(io.BytesIO(payload), last, 8192, first)
        self.assertEqual(_safe_out_of_range_options(
            b"".join(first) + b"\n" + b"".join(last)),
            ("new_supported_setting",))

    def test_orca_stdout_project_error_is_categorized_without_leaking_data(self):
        import io
        class FakeProcess:
            returncode = 238
            stdout = io.BytesIO(
                b"Param values in 3mf/config error. /secret/user/print.3mf API_KEY=private"
            )
            stderr = io.BytesIO(b"")
            def wait(self, timeout=None):
                return self.returncode
        with patch("slicer_worker.orca_runner.subprocess.Popen", return_value=FakeProcess()):
            with self.assertRaises(WorkerError) as error:
                run_orca(self.binary, self.root)
        self.assertEqual(
            str(error.exception),
            "OrcaSlicer CLI exited: native-project-settings-invalid."
        )
        self.assertNotIn("private", str(error.exception))

    def test_unclassified_orca_exit_238_has_stable_safe_reason(self):
        import io
        class FakeProcess:
            returncode = 238
            stdout = io.BytesIO(b"Sensitive unknown crash output from user model")
            stderr = io.BytesIO(b"")
            def wait(self, timeout=None):
                return self.returncode
        with patch("slicer_worker.orca_runner.subprocess.Popen", return_value=FakeProcess()):
            with self.assertRaisesRegex(WorkerError, "cli-validation-exit-238"):
                run_orca(self.binary, self.root)

    def test_exit_239_keeps_safe_validation_classification(self):
        import io

        class FakeProcess:
            returncode = 239
            stderr = io.BytesIO(b"Private printer file location")
            stdout = io.BytesIO(b"")
            def wait(self, timeout=None):
                return self.returncode

        with patch("slicer_worker.orca_runner.subprocess.Popen", return_value=FakeProcess()):
            with self.assertRaisesRegex(WorkerError, "cli-validation-exit-239"):
                run_orca(self.binary, self.root)

    def test_cli_failure_does_not_echo_private_stderr(self):
        import io
        class FakeProcess:
            returncode = 1
            stderr = io.BytesIO(b"Sensitive printer configuration: API_KEY=not-for-logs")
            def wait(self, timeout=None):
                return self.returncode
        with patch("slicer_worker.orca_runner.subprocess.Popen", return_value=FakeProcess()):
            with self.assertRaises(WorkerError) as error:
                run_orca(self.binary, self.root)
        self.assertEqual(str(error.exception), "OrcaSlicer CLI exited: engine-exited.")
        self.assertNotIn("not-for-logs", str(error.exception))
