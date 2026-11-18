"""Offline regression coverage for the real-engine Creality matrix.

These unit tests do not call a slicer binary, Docker, networks or printers.
The separately invoked staging harness exercises the approved actual binary.
"""
import unittest
from unittest.mock import patch

from slicer_worker.creality_diagnostics import _cases, run_matrix, _known_validation_reason


class CrealityDiagnosticMatrixTests(unittest.TestCase):
    def test_upstream_material_validation_reason_is_allowlisted(self):
        self.assertEqual(_known_validation_reason(
            b"got error when validate: Can not print multiple filaments which have "
            b"large difference of temperature together. Otherwise, the nozzle "
            b"may be blocked"), "incompatible-material-temperature-ranges")
        self.assertEqual(_known_validation_reason(
            b"got error when validate: The mixed filament references a filament "
            b"that no longer exists."), "missing-mixed-filament-reference")
        self.assertIsNone(_known_validation_reason(
            b"got error when validate: private/token=DO_NOT_EXPORT"))

    def test_isolation_cases_are_fixed_and_predictable(self):
        options = _cases({
            "nozzle_temperature": ["210", "220"],
            "filament_map": ["1", "1", "1", "1"],
            "filament_settings_id": ["grey", "yellow", "grey", "yellow"],
            "enable_prime_tower": "1",
        })
        self.assertEqual([name for name, _edits, _desc in options], [
            "baseline", "no-explicit-filament-map",
            "explicit-single-nozzle", "tower-disabled",
            "normalised-filament-scalars", "identical-filament-parameters",
        ])
        self.assertEqual(options[1][1], {"filament_map": None})
        self.assertEqual(options[2][1], {"filament_map": ["1", "1", "1", "1"]})
        self.assertEqual(options[3][1], {"enable_prime_tower": "0"})

    @patch("slicer_worker.creality_diagnostics.compare_to_bundled_reference", return_value={"reference_source": "bundled-sanitised-7.3.2.6412"})
    @patch("slicer_worker.creality_diagnostics.single_material_control", return_value=b"single private geometry")
    @patch("slicer_worker.creality_diagnostics._engine_run")
    @patch("slicer_worker.creality_diagnostics._repack")
    @patch("slicer_worker.creality_diagnostics._read_project")
    @patch("slicer_worker.creality_diagnostics.configured_engines")
    def test_report_contains_no_private_profiles_or_raw_output(
            self, engines, project, repack, execute, single, reference):
        engines.return_value = {"crealityprint": {
            "binary": "/approved/AppRun", "version": "7.3.1",
            "binary_sha256": "a" * 64}}
        original = b"test 3MF bytes holding SECRET-STL-COORDINATES"
        project.return_value = original, {
            "filament_map": ["1", "1", "1", "1"],
            "filament_settings_id": ["grey", "yellow", "grey", "yellow"],
            "nozzle_temperature": ["210", "220", "210", "220"]}
        repack.return_value = b"changed, but still private"
        execute.return_value = {
            "status": "failed", "exit_code": 205,
            "native_error": "CLI_VALIDATE_ERROR (-51)",
            "validation_category": "filament",
        }
        report = run_matrix("/tmp/test.3mf", timeout_seconds=30)
        self.assertEqual(len(report["test_results"]), 7)
        self.assertEqual(report["reference"]["reference_source"], "bundled-sanitised-7.3.2.6412")
        reference.assert_called_once_with(original)
        import json
        encoded = json.dumps(report)
        self.assertNotIn("SECRET-STL-COORDINATES", encoded)
        self.assertNotIn("nozzle_temperature", encoded)
        self.assertEqual(report["test_results"][0]["case"], "single-model-single-material")
        self.assertEqual(report["test_results"][0]["exit_code"], 205)
        self.assertEqual(report["test_results"][0]["validation_category"], "filament")
        self.assertEqual(execute.call_count, 7)


if __name__ == "__main__":
    unittest.main()
