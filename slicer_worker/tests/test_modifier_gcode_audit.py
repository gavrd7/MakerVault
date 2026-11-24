"""Require real XY positive-E deposition within modifier volumes, not comments."""
import unittest

from slicer_worker.modifier_gcode_audit import (
    audit_modifier_positive_e, modifier_bounds,
)
from slicer_worker.runner import WorkerError
from slicer_worker.tests.test_modifier_3mf_validation import fixture, composite_fixture


class ModifierGcodeCoverageTests(unittest.TestCase):
    def setUp(self):
        self.project = fixture()

    def test_valid_paths_reach_each_bounded_region(self):
        program = [b"G90", b"M83", b"G1 Z5 F900"]
        for i in range(20):
            program.append(("G1 X%d Y%d E0.8" % (2 + i % 4, 3 + i % 4)).encode())
        result = audit_modifier_positive_e(
            b"\n".join(program), self.project, "orcaslicer")
        self.assertEqual(result["modifier_count"], 1)
        self.assertGreater(result["modifier_region_paths"][0], 0)

    def test_missing_region_and_comment_only_signals_are_rejected(self):
        for code in (
            b"; all modifiers accepted\nG1 X2 Y2 E1\n",
            b"G90\nM83\n" + b"G1 X100 Y100 Z5 E1\n" * 20,
            b"G90\nM83\n" + b"G1 X2 Y2 Z50 E1\n" * 20,
            b"G90\nM83\n" + b"G1 X2 Y2 Z5 E-1\n" * 20,
            b"G90\nM83\n" + b"G1 X2 Y2 Z5\n" * 20,
        ):
            with self.subTest(code=code[:25]), self.assertRaises(WorkerError):
                audit_modifier_positive_e(code, self.project, "orcaslicer")

    def test_relative_xyz_is_resolved_and_g92_only_resets_position(self):
        code = b"\n".join([
            b"G90", b"M83", b"G92 X0 Y0 Z5",
            b"G91",
            *([b"G1 X0.2 Y0.2 E0.1"] * 15),
        ])
        result = audit_modifier_positive_e(code, self.project, "orcaslicer")
        self.assertEqual(result["modifier_region_paths"], [15])

    def test_native_negative_requires_empty_deposition_inside_subtraction_bounds(self):
        project = composite_fixture(negative=True)
        # Real subtraction can remove every extrusion path inside the
        # negative mesh; the remaining printable model still deposits outside.
        outside = [b"G90", b"M83", b"G0 X20 Y20 Z5"]
        outside.extend(("G1 X%d Y%d E0.8" % (20 + i % 4, 20 + i % 4)).encode()
                       for i in range(20))
        result = audit_modifier_positive_e(
            b"\n".join(outside), project, "orcaslicer")
        self.assertEqual(result["negative_volume_count"], 1)
        self.assertEqual(result["modifier_region_paths"], [0])

        # Extrusions on the cavity boundary form legitimate shell contours.
        boundary = [b"G90", b"M83", b"G0 X0 Y0 Z5"]
        boundary.extend(("G1 X%d Y0 E0.8" % (i % 4)).encode()
                        for i in range(20))
        audited = audit_modifier_positive_e(
            b"\n".join(boundary), project, "orcaslicer")
        self.assertEqual(audited["modifier_region_paths"], [0])

        inside = [b"G90", b"M83", b"G0 X2 Y2 Z5"]
        inside.extend(("G1 X%d Y%d E0.8" % (2 + i % 4, 2 + i % 4)).encode()
                      for i in range(20))
        with self.assertRaisesRegex(WorkerError, "deposits material"):
            audit_modifier_positive_e(
                b"\n".join(inside), project, "orcaslicer")

    def test_invalid_project_must_not_be_trusted(self):
        with self.assertRaises(WorkerError):
            modifier_bounds(b"not a valid 3MF", "orcaslicer")


if __name__ == "__main__":
    unittest.main()
