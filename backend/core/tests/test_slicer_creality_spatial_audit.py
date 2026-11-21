"""Spatial K2 painting evidence must not be inferred from hashes or printer code."""
import json

from django.test import SimpleTestCase

from core.slicer_creality_spatial_audit import (
    painted_triangle_bounds, spatial_comparison, spatial_deposition_cells,
)
from core.management.commands.diagnose_creality_paint_fixture import (
    _fixture_project,
)
from core.management.commands.diagnose_creality_paint_features import (
    _cantilever_fixture_stl,
)

BOUNDS = {"x_mm": [0, 4], "y_mm": [0, 4], "z_mm": [0, 10],
          "painted_triangles": 2}


class CrealitySpatialAuditTests(SimpleTestCase):
    def test_relative_gcode_support_deposition_inside_outside_and_exclusions(self):
        gcode = (
            b"M83\nG90\nT1\n; FEATURE: Support\n"
            b"G1 X1 Y1 Z1 E.25\nG1 X2 Y2 E.5\n"
            b"G1 X8 Y8 E-.2\nG1 X9 Y9 E.25\n"
            b"; FEATURE: Outer wall\nG1 X2 Y2 E.3\n"
        )
        observed = spatial_deposition_cells(
            gcode, role="support", bounds=BOUNDS, margin_mm=0)
        self.assertEqual(observed["matching_deposition_moves"], 3)
        self.assertEqual(observed["inside_painted_xy_moves"], 2)
        self.assertEqual(observed["outside_painted_xy_moves"], 1)
        self.assertEqual(observed["observed_extrusion_mode"], "relative")
        self.assertEqual(observed["unknown_extrusion_mode_moves"], 0)
        other_tool = spatial_deposition_cells(
            gcode, role="support", tool=0, bounds=BOUNDS)
        self.assertEqual(other_tool["matching_deposition_moves"], 0)

    def test_absolute_extrusion_after_g92_and_relative_xy(self):
        gcode = (
            b"G90\nM82\nG92 E0\nG1 X1 Y1 E1\n"
            b"G1 X2 Y2 E0.5\nG92 E0\nG91\n"
            b"G1 X1 Y1 E2\nG1 X5 Y5 E3\n"
        )
        observed = spatial_deposition_cells(
            gcode, bounds=BOUNDS, margin_mm=0)
        self.assertEqual(observed["matching_deposition_moves"], 3)
        self.assertEqual(observed["inside_painted_xy_moves"], 2)
        self.assertEqual(observed["outside_painted_xy_moves"], 1)
        self.assertEqual(observed["observed_extrusion_mode"], "absolute")

    def test_comparison_requires_spatial_change_not_only_nonidentical_gcode(self):
        control = b"M83\nG90\n; TYPE: Support\nG1 X1 Y1 E1\n"
        painted = control + b"G1 X2 Y2 E.25\n"
        comparison = spatial_comparison(
            painted, control, BOUNDS, role="support", margin_mm=0)
        self.assertTrue(comparison["spatial_effect_observed"])
        self.assertGreater(
            comparison["changed_voxel_deposition_count_inside_painted_xy"], 0)
        self.assertEqual(
            comparison["changed_voxel_deposition_count_outside_painted_xy"], 0)
        same = spatial_comparison(control, control, BOUNDS, role="support")
        self.assertFalse(same["spatial_effect_observed"])
        self.assertNotIn("cells", same["painted"])

    def test_reject_unknown_role_and_incomplete_absolute_gcode(self):
        with self.assertRaises(ValueError):
            spatial_deposition_cells(b"M83\n", role="secret",
                                     bounds=BOUNDS)
        unknown = spatial_deposition_cells(
            b"G90\nG1 X1 Y1 E1\n", bounds=BOUNDS)
        self.assertEqual(unknown["matching_deposition_moves"], 0)
        self.assertEqual(unknown["unknown_extrusion_mode_moves"], 1)

    def test_real_fixture_project_bakes_paint_tag_coordinates(self):
        raw = _cantilever_fixture_stl()
        machine = json.dumps({
            "type": "machine", "name": "Synthetic K2",
            "printable_height": "260",
            "printable_area": ["0x0", "260x0", "260x260", "0x260"],
            "purge_in_prime_tower": "0",
        }).encode()
        process = json.dumps({
            "type": "process", "name": "Synthetic process",
            "enable_prime_tower": "1", "prime_tower_width": "40",
        }).encode()
        filaments = [
            json.dumps({
                "type": "filament", "name": name, "filament_type": "PLA",
                "nozzle_temperature": temp,
            }).encode()
            for name, temp in (("Dark", "210"), ("Light", "220"))
        ]
        for feature, attribute in (
                ("baseline", "paint_color"), ("support", "paint_supports"),
                ("seam", "paint_seam"), ("fuzzy", "paint_fuzzy_skin")):
            with self.subTest(feature=feature):
                project, _ = _fixture_project(
                    raw, feature, machine=machine, process=process,
                    filaments=filaments, width=260, depth=260)
                bounds = painted_triangle_bounds(project, attribute)
                self.assertGreater(bounds["painted_triangles"], 0)
                self.assertLessEqual(bounds["x_mm"][0], bounds["x_mm"][1])
                self.assertLessEqual(bounds["y_mm"][0], bounds["y_mm"][1])
                self.assertTrue(0 <= bounds["z_mm"][0] <= 260)
                self.assertTrue(0 <= bounds["z_mm"][1] <= 260)

    def test_spatial_only_cli_requires_deep_and_rejects_only(self):
        from django.core.management.base import CommandParser, CommandError
        from core.management.commands.diagnose_creality_paint_fixture import Command
        parser = CommandParser(prog="diagnose_creality_paint_fixture")
        Command().add_arguments(parser)
        ids = [
            "--printer-profile-id", "580c1d65-ee1f-4919-b2ea-93a98cd33e1a",
            "--process-profile-id", "42b0025a-20f2-485e-8ca4-7caca3e994f9",
            "--filament-profile-id", "cf892271-178c-4c6a-a104-58c8d016acc8",
            "--filament-profile-id", "b00a0dc9-fe2c-4653-a1df-dfb8d7429a3e",
        ]
        for args in (["--spatial-only"], ["--deep", "--spatial-only",
                                          "--only", "support"]):
            with self.subTest(flags=args), self.assertRaises(CommandError):
                Command().handle(**vars(parser.parse_args(ids + args)))
        valid = vars(parser.parse_args(ids + ["--spatial-only", "--deep"]))
        self.assertTrue(valid["spatial_only"])
        self.assertTrue(valid["deep"])
