"""Offline Creality feature diagnostic invariants (no engine required)."""
import io
import json
import zipfile
from xml.etree import ElementTree as ET

from django.test import SimpleTestCase

from core.management.commands.diagnose_creality_paint_features import (
    _metrics, _patch_for_model, _native_project_audit,
    _geometry_control_project, _layer_band_audit,
    _feature_role_audit, _gcode_effective_settings,
    _cantilever_fixture_stl, _cantilever_support_marker,
    _cantilever_wall_marker,
)
from core.slicer_approval import fixture_stl
from core.slicer_mesh import inspect_stl
from core.slicer_plate_3mf import _triangles


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

    def test_geometry_control_removes_only_semantic_attribute(self):
        ns = "{http://schemas.microsoft.com/3dmanufacturing/core/2015/02}"
        model = ('<model xmlns="http://schemas.microsoft.com/3dmanufacturing/core/2015/02">'
                 '<resources><object id="1"><mesh><triangles>'
                 '<triangle v1="0" v2="1" v3="2" paint_color="8" '
                 'paint_supports="4" paint_seam="8"/>'
                 '</triangles></mesh></object></resources></model>')
        source = io.BytesIO()
        with zipfile.ZipFile(source, "w") as archive:
            archive.writestr("3D/3dmodel.model", model)
            archive.writestr("Metadata/project_settings.config", '{"enable_support":"1"}')
        result, count = _geometry_control_project(source.getvalue(), "support")
        self.assertEqual(count, 1)
        with zipfile.ZipFile(io.BytesIO(result)) as archive:
            self.assertEqual(json.loads(archive.read("Metadata/project_settings.config")),
                             {"enable_support": "1"})
            root = ET.fromstring(archive.read("3D/3dmodel.model"))
        triangle = next(root.iter(ns + "triangle"))
        self.assertEqual(triangle.attrib["paint_color"], "8")
        self.assertEqual(triangle.attrib["paint_seam"], "8")
        self.assertNotIn("paint_supports", triangle.attrib)
        with self.assertRaises(ValueError):
            _geometry_control_project(result, "support")

    def test_variable_layer_band_audit_locates_height_within_interval(self):
        gcode = (b";Z:0.2\n;Z:0.4\n;Z:0.6\n;Z:0.72\n"
                 b";Z:0.84\n;Z:1.04\n")
        result = _layer_band_audit(gcode, 0.6, 0.9)
        self.assertTrue(result["band_target_observed"])
        self.assertEqual(result["interior_target_steps"], 2)
        self.assertEqual(result["interior_observed_steps_mm"], [0.12])
        self.assertEqual(result["outside_observed_steps_mm"], [0.2])
        self.assertFalse(_layer_band_audit(gcode, 2.0, 3.0)["band_target_observed"])

    def test_feature_roles_count_support_extrusions_not_markers_alone(self):
        gcode = (b"; FEATURE: Outer wall\nG1 X1 Y2 E0.1\n"
                 b"; FEATURE: Support\nG1 X3 Y3 E0.2\n"
                 b"G1 E-0.3\nG1 X4 Y4\n"
                 b";TYPE:Support interface\nG1 X4 Y5 E0.4\n"
                 b"; FEATURE: Sparse infill\nG1 X6 E0.5\n")
        audit = _feature_role_audit(gcode)
        self.assertEqual(audit["feature_role_tags"], 4)
        self.assertEqual(audit["recognized_role_tag_counts"]["outer wall"], 1)
        self.assertEqual(audit["recognized_role_tag_counts"]["support"], 1)
        self.assertEqual(audit["recognized_role_tag_counts"]["support interface"], 1)
        self.assertEqual(audit["recognized_role_tag_counts"]["sparse infill"], 1)
        self.assertEqual(audit["extrusion_xy_moves_by_role"]["support"], 2)
        self.assertEqual(audit["extrusion_xy_moves_by_role"]["outer_wall"], 1)
        self.assertEqual(audit["extrusion_xy_moves_by_role"]["other"], 1)

    def test_gcode_config_audit_reads_safe_keys_only(self):
        gcode = (b"; flush_volumes_matrix = 0,370,175,0\n"
                 b"; flush_multiplier = 1.25\n"
                 b"; purge_in_prime_tower = 0\n"
                 b"; change_filament_gcode = sensitive G-code macro\n")
        audit = _gcode_effective_settings(gcode)
        self.assertEqual(audit["flush_multiplier"], "1.25")
        self.assertEqual(audit["purge_in_prime_tower"], "0")
        self.assertEqual(len(audit["flush_matrix_gcode_header_sha256"]), 64)
        self.assertNotIn("change_filament_gcode", audit)
        self.assertNotIn("sensitive", str(audit))

    def test_deterministic_cantilever_fixture_paints_elevated_underside(self):
        first = _cantilever_fixture_stl()
        self.assertEqual(first, _cantilever_fixture_stl())
        mesh = inspect_stl(first)
        self.assertEqual(mesh["triangles"], 20)
        self.assertEqual(mesh["size_mm"], [30.0, 12.0, 25.0])
        marker = _cantilever_support_marker(first)
        signature, _face, _polygon, height = _patch_for_model(first)
        self.assertEqual(marker["signature"], signature)
        self.assertEqual(height, 25.0)
        patch = marker["regions"][0]["patches"][0]
        triangle = list(_triangles(first))[patch["face"]]
        self.assertTrue(all(abs(vertex[2] - 20.) < 1e-5
                            for vertex in triangle))
        self.assertTrue(all(abs(point[2] - 20.) < 1e-5
                            for point in patch["polygon"]))
        self.assertGreater(sum(vertex[0] for vertex in triangle) / 3, 13)

    def test_wall_fixture_targets_exterior_vertical_face(self):
        mesh = _cantilever_fixture_stl()
        marker = _cantilever_wall_marker(mesh)
        self.assertEqual(marker["signature"], _patch_for_model(mesh)[0])
        region = marker["regions"][0]
        self.assertEqual(region["slot"], 0)
        patch = region["patches"][0]
        triangle = list(_triangles(mesh))[patch["face"]]
        self.assertTrue(all(abs(point[1]) < 1e-5 for point in triangle))
        self.assertGreater(max(p[2] for p in triangle) -
                           min(p[2] for p in triangle), 15)
        self.assertEqual(len(patch["polygon"]), 3)
