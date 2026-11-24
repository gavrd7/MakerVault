"""Regression checks for exact-binary composite G-code evidence.

These tests do not approve any engine for production. They verify that the
diagnostic accounts for real positive-E moves and records feature attribution.
"""
import unittest

from slicer_worker.composite_acceptance_probe import two_model_region_extrusion, bambu_output_placement_shift
import io
import zipfile
from pathlib import Path
from tempfile import TemporaryDirectory
from slicer_worker.single_negative_diagnostic import _cavity_y_bands, _build_xy_translation


class CompositeNativeEvidenceTests(unittest.TestCase):
    def test_extrusion_is_attributed_to_both_independent_printables(self):
        code = b"\n".join([
            b"G90", b"M83", b"G0 X85 Y105 Z15",
            b"; FEATURE: Internal infill",
            b"G1 X95 Y105 E1.50",
            b"G1 X100 Y105 E0.50",
            b"G0 X125 Y105",
            b"; FEATURE: Outer wall",
            b"G1 X135 Y105 E2.25",
            b"; FEATURE: Support",
            b"G1 X140 Y105 E0.75",
        ])
        evidence = two_model_region_extrusion(code)
        self.assertEqual(evidence["counts"], {"left": 2, "right": 2})
        self.assertAlmostEqual(evidence["totals"]["left"], 2.0)
        self.assertAlmostEqual(evidence["totals"]["right"], 3.0)
        self.assertAlmostEqual(evidence["features"]["left"]["Internal infill"], 2.0)
        self.assertAlmostEqual(evidence["features"]["right"]["Outer wall"], 2.25)
        self.assertAlmostEqual(evidence["features"]["right"]["Support"], 0.75)

    def test_retraction_travel_and_out_of_band_do_not_prove_model_effects(self):
        code = b"\n".join([
            b"G90", b"M83", b"G0 X85 Y105 Z15",
            b"G1 X95 Y105 E-1",
            b"G0 X100 Y105",
            b"G1 X110 Y105 E2",
            b"G0 X125 Y105 Z25",
            b"G1 X135 Y105 E3",
            b"G0 X125 Y105 Z15",
            b"G1 X135 Y105 E1",
        ])
        evidence = two_model_region_extrusion(code)
        self.assertEqual(evidence["counts"], {"left": 0, "right": 1})
        self.assertAlmostEqual(evidence["totals"]["right"], 1.0)

    def test_negative_cut_boundary_walls_do_not_count_as_filled_cavity(self):
        # The 3MF negative spans Y=100..120, so new walls on those faces
        # are legitimate even though the strict cavity interior must be empty.
        code = b"\n".join([
            b"G90", b"M83", b"G0 X85 Y100 Z15",
            b"; FEATURE: Inner wall",
            b"G1 X95 Y100 E3",
            b"G0 X85 Y120",
            b"G1 X95 Y120 E3",
        ])
        result = two_model_region_extrusion(code)
        self.assertEqual(result["counts"], {"left": 0, "right": 0})

    def test_bambu_negative_cavity_diagnostic_distinguishes_inner_and_boundary_paths(self):
        gcode = b"\n".join([
            b"G90", b"M83", b"G0 X123 Y109 Z15",
            b"; FEATURE: Sparse infill", b"G1 X133 Y109 E1.25",
            b"G0 X123 Y99", b"; FEATURE: Inner wall",
            b"G1 X133 Y99 E2.5",
            b"G0 X123 Y121", b"G1 X133 Y121 E0.75",
            b"G0 X123 Y109", b"G1 X133 Y109 E-0.5",
        ])
        result = _cavity_y_bands(gcode)
        self.assertEqual(result["108"]["count"], 1)
        self.assertAlmostEqual(result["108"]["E"], 1.25)
        self.assertEqual(result["108"]["features"], {"Sparse infill": 1.25})
        self.assertEqual(result["098"]["features"], {"Inner wall": 2.5})
        self.assertEqual(result["120"]["features"], {"Inner wall": 0.75})

    def test_bambu_region_sampling_follows_slicer_recentered_placement(self):
        gcode = b"\n".join([
            b"G90", b"M83", b"G0 X103 Y123 Z15",
            b"; FEATURE: Sparse infill", b"G1 X113 Y123 E1.25",
            b"G0 X143 Y123", b"G1 X153 Y123 E0.75",
        ])
        # A Bambu export can shift the composite by +18mm from the 220mm
        # fixture to its 256mm native plate; the old fixed sample misses it.
        raw = two_model_region_extrusion(gcode)
        self.assertEqual(raw["counts"], {"left": 0, "right": 0})
        shifted = two_model_region_extrusion(gcode, shift_x=18, shift_y=18)
        self.assertEqual(shifted["counts"], {"left": 1, "right": 1})
        self.assertAlmostEqual(shifted["totals"]["left"], 1.25)
        self.assertAlmostEqual(shifted["totals"]["right"], 0.75)

    def test_bambu_output_shift_reads_its_native_3mf_placement_not_assumptions(self):
        ns = "http://schemas.microsoft.com/3dmanufacturing/core/2015/02"
        template = ('<model xmlns="' + ns + '" unit="millimeter">'
                    '<resources/><build><item objectid="3" transform="'
                    '1 0 0 0 1 0 0 0 1 18 18 0"/></build></model>')
        with TemporaryDirectory() as folder:
            filename = Path(folder) / "native-output.3mf"
            with zipfile.ZipFile(filename, "w") as package:
                package.writestr("3D/3dmodel.model", template)
            self.assertEqual(bambu_output_placement_shift(filename), (18, 18))
            with zipfile.ZipFile(filename, "w") as package:
                package.writestr("3D/3dmodel.model",
                                 template.replace("1 0 0 0 1", "0 1 0 0 1"))
            from slicer_worker.runner import WorkerError
            with self.assertRaisesRegex(WorkerError, "unexpected native geometry"):
                bambu_output_placement_shift(filename)

    def test_single_model_native_build_delta_recovers_bambu_recentered_cut(self):
        ns = "http://schemas.microsoft.com/3dmanufacturing/core/2015/02"
        def project(dx, dy, dz):
            xml = ('<model xmlns="' + ns + '" unit="millimeter">'
                   '<resources/><build><item objectid="1" transform="'
                   f'1 0 0 0 1 0 0 0 1 {dx} {dy} {dz}"/></build></model>')
            return xml
        with TemporaryDirectory() as folder:
            before = Path(folder) / "source.3mf"
            after = Path(folder) / "result.3mf"
            with zipfile.ZipFile(before, "w") as archive:
                archive.writestr("3D/3dmodel.model", project(90, 110, 0))
            with zipfile.ZipFile(after, "w") as archive:
                archive.writestr("3D/3dmodel.model", project(128, 128, 15))
            source_xy = _build_xy_translation(before)
            result_xy = _build_xy_translation(after)
            self.assertEqual(tuple(result_xy[i]-source_xy[i] for i in (0,1)),
                             (38, 18))
        gcode = b"\n".join([
            b"G90", b"M83", b"G0 X123 Y127 Z15",
            b"; FEATURE: Sparse infill", b"G1 X133 Y127 E1.2",
        ])
        result = _cavity_y_bands(gcode, centre_x=128, centre_y=128)
        self.assertAlmostEqual(result["126"]["E"], 1.2)
        self.assertEqual(_cavity_y_bands(gcode), {})

    def test_absolute_extrusion_reset_only_counts_positive_e(self):
        code = b"\n".join([
            b"G90", b"M82", b"G92 E0",
            b"G0 X85 Y105 Z15",
            b"G1 X95 Y105 E1.5",
            b"G1 X100 Y105 E1",
            b"G92 E0",
            b"G1 X95 Y105 E0.75",
        ])
        evidence = two_model_region_extrusion(code)
        self.assertEqual(evidence["counts"]["left"], 2)
        self.assertAlmostEqual(evidence["totals"]["left"], 2.25)


if __name__ == "__main__":
    unittest.main()
