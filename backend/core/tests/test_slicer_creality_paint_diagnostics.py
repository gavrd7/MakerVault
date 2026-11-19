"""Offline Creality feature diagnostic invariants (no engine required)."""
import io
import json
import zipfile

from django.test import SimpleTestCase

from core.management.commands.diagnose_creality_paint_features import (
    _metrics, _patch_for_model, _native_project_audit,
)
from core.slicer_approval import fixture_stl


class CrealityPaintingDiagnosticTests(SimpleTestCase):
    def test_generated_patch_is_bounded_and_fingerprinted(self):
        signature, face, polygon, height = _patch_for_model(fixture_stl())
        self.assertIn(":", signature)
        self.assertGreaterEqual(face, 0)
        self.assertEqual(len(polygon), 3)
        self.assertGreater(height, 3)
        self.assertTrue(all(len(point) == 3 for point in polygon))

    def test_motion_compare_does_not_count_changed_header_as_toolpath(self):
        first = _metrics(b"; generated: 1\n;Z:0.2\nT0\nG1 X1 Y1 E0.1\n")
        second = _metrics(b"; generated: 2\n;Z:0.2\nT0\nG1 X1 Y1 E0.1\n")
        third = _metrics(b"; generated: 2\n;Z:0.2\nT0\nG1 X1 Y1 E0.3\n")
        self.assertNotEqual(first["gcode_sha256"], second["gcode_sha256"])
        self.assertEqual(first["motion_sha256"], second["motion_sha256"])
        self.assertNotEqual(first["motion_sha256"], third["motion_sha256"])
        self.assertEqual(first["tool0_selects"], 1)
        self.assertEqual(first["g1_with_extrusion"], 1)

    def test_motion_hash_normalizes_spacing_and_ignores_comments(self):
        first = _metrics(b"; timestamp: one\nT0\nG1 X1 Y1 E0.1 ; extrusion\n")
        second = _metrics(b"; timestamp: two\n t0  \n g1   x1  y1   e0.1\n")
        changed = _metrics(b"T0\nG1 X1 Y1 E0.2\n")
        self.assertEqual(first["motion_sha256"], second["motion_sha256"])
        self.assertNotEqual(first["motion_sha256"], changed["motion_sha256"])

    def test_machine_commands_audited_separately_from_motion(self):
        a = _metrics(b"T0\nG1 X1 Y1 E0.1\nM900 K0.02\n")
        b = _metrics(b"T0\nG1 X1 Y1 E0.1\nM900 K0.03\n")
        self.assertEqual(a["motion_sha256"], b["motion_sha256"])
        self.assertNotEqual(a["machine_command_sha256"],
                            b["machine_command_sha256"])

    def test_native_flushing_audit_uses_directional_matrix_and_scalar(self):
        values = {"flush_volumes_matrix": [0, 370, 140, 140,
                                            175, 0, 140, 140,
                                            140, 140, 0, 140,
                                            140, 140, 140, 0],
                  "flush_multiplier": "1.25",
                  "flush_volumes_changed": "1",
                  "support_type": "normal(manual)",
                  "enable_support": "1"}
        out = io.BytesIO()
        with zipfile.ZipFile(out, "w") as archive:
            archive.writestr("Metadata/project_settings.config", json.dumps(values))
        audit = _native_project_audit(out.getvalue())
        self.assertEqual(audit["flush_t0_to_t1_mm3"], 462.5)
        self.assertEqual(audit["flush_t1_to_t0_mm3"], 218.75)
        self.assertEqual(audit["flush_volumes_changed"], "1")
        self.assertEqual(audit["support_enabled"], "1")
