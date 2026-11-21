import os
import io
import zipfile
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch

from slicer_worker.probe import fixture_stl, run_probe, _validate_gcode, _verify_two_native_object_effects
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

    def test_native_object_effects_measure_real_extrusion_not_comments(self):
        gcode = self.root / "two-cubes.gcode"
        lines = ["M83", "G90"]
        for i in range(40):
            lines.append(f"G1 X{75 + i % 10} Y{110 + i % 5} E0.08")
        for i in range(70):
            lines.append(f"G1 X{145 + i % 10} Y{110 + i % 5} E0.12")
        gcode.write_text("\n".join(lines) + "\n")
        evidence = _verify_two_native_object_effects(gcode)
        self.assertGreater(evidence["effective_extrusion_ratio"], 2)
        self.assertEqual(evidence["left_moves"], 40)
        self.assertEqual(evidence["right_moves"], 70)
        reversed_gcode = self.root / "reversed-cubes.gcode"
        reversed_lines = ["M83", "G90"]
        for i in range(70):
            reversed_lines.append(f"G1 X{75 + i % 10} Y{110 + i % 5} E0.12")
        for i in range(40):
            reversed_lines.append(f"G1 X{145 + i % 10} Y{110 + i % 5} E0.08")
        reversed_gcode.write_text("\n".join(reversed_lines) + "\n")
        reversed_evidence = _verify_two_native_object_effects(reversed_gcode, reverse=True)
        self.assertLess(reversed_evidence["effective_extrusion_ratio"], 0.8)
        with self.assertRaisesRegex(WorkerError, "not proven effective"):
            _verify_two_native_object_effects(reversed_gcode)
        with self.assertRaisesRegex(WorkerError, "not proven effective"):
            _verify_two_native_object_effects(gcode, reverse=True)
        bad = self.root / "identical.gcode"
        equal = ["M83", "G90"]
        for center in (75, 145):
            for i in range(40):
                equal.append(f"G1 X{center + i % 10} Y{110 + i % 5} E0.1")
        bad.write_text("\n".join(equal) + "\n")
        with self.assertRaisesRegex(WorkerError, "not proven effective"):
            _verify_two_native_object_effects(bad)

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

    def test_two_object_3mf_requires_real_separated_extrusion(self):
        ns = "http://schemas.microsoft.com/3dmanufacturing/core/2015/02"
        vertices = '<vertices><vertex x="0" y="0" z="0"/><vertex x="10" y="0" z="0"/><vertex x="0" y="10" z="0"/></vertices>'
        faces = '<triangles><triangle v1="0" v2="1" v3="2"/></triangles>'
        objects = "".join(f'<object id="{i}" type="model"><mesh>{vertices}{faces}</mesh></object>'
                          for i in (1, 2))
        items = ('<item objectid="1" transform="1 0 0 0 1 0 0 0 1 80 100 0"/>'
                 '<item objectid="2" transform="1 0 0 0 1 0 0 0 1 150 100 0"/>')
        content = (f'<model xmlns="{ns}" unit="millimeter"><resources>{objects}</resources>'
                   f'<build>{items}</build></model>').encode()
        fixture = self.root / "two-models.3mf"
        with zipfile.ZipFile(fixture, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("3D/3dmodel.model", content)
            archive.writestr("[Content_Types].xml", "<Types/>")
            archive.writestr("_rels/.rels", "<Relationships/>")
            archive.writestr("Metadata/model_settings.config",
                '<config><plate><metadata key="plater_id" value="1"/>'
                '<model_instance><metadata key="object_id" value="1"/>'
                '<metadata key="instance_id" value="0"/>'
                '<metadata key="identify_id" value="1"/></model_instance>'
                '<model_instance><metadata key="object_id" value="2"/>'
                '<metadata key="instance_id" value="0"/>'
                '<metadata key="identify_id" value="2"/></model_instance>'
                '</plate></config>')

        def fake_runner(binary, root, *, timeout_seconds):
            self.assertTrue((root / "input.3mf").is_file())
            self.assertFalse((root / "input.stl").exists())
            (root / "output.gcode").write_bytes(
                b"G1 X81 Y100 E1.0\nG1 X151 Y100 E2.0\n"
            )
            return {"status": "completed"}

        with patch("slicer_worker.probe.ENGINES", {"crealityprint": fake_runner}):
            result = run_probe(**self.kwargs(), model=str(fixture), expected_objects=2)
        self.assertEqual(result["status"], "passed")
        self.assertEqual(result["object_count"], 2)
        self.assertEqual(result["fixture"], "makervault-two-object-3mf-v1")

        def incomplete(binary, root, *, timeout_seconds):
            (root / "output.gcode").write_bytes(b"G1 X81 Y100 E1.0\nG1 X85 Y100 E2.0\n")
            return {"status": "completed"}

        with patch("slicer_worker.probe.ENGINES", {"crealityprint": incomplete}):
            with self.assertRaisesRegex(WorkerError, "extrusion coverage insufficient"):
                run_probe(**self.kwargs(), model=str(fixture), expected_objects=2)

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
