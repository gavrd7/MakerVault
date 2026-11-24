"""Require real XY positive-E deposition within modifier volumes, not comments."""
import unittest
import math
import io
import zipfile
from xml.etree import ElementTree as ET

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

        # The fixture region is a tetrahedron: at Z=5 its true section
        # satisfies X>0, Y>0, X+Y<5. The old 2..5 path was in the AABB,
        # but outside that mesh, so it correctly did not trigger rejection.
        inside = [b"G90", b"M83", b"G0 X1 Y1 Z5"]
        inside.extend(("G1 X%d Y%d E0.8" % (1 + i % 2, 1 + i % 2)).encode()
                      for i in range(20))
        with self.assertRaisesRegex(WorkerError, "deposits material"):
            audit_modifier_positive_e(
                b"\n".join(inside), project, "orcaslicer")

    def test_bambu_negative_deposition_logs_only_aggregate_bands(self):
        project = composite_fixture(negative=True)
        interior = [b"G90", b"M83", b"G0 X1 Y1 Z5"]
        interior.extend((b"G1 X2 Y2 E0.5" if i % 2 == 0 else
                         b"G1 X1 Y1 E0.5") for i in range(20))
        with self.assertLogs("slicer_worker.modifier_gcode_audit", level="WARNING") as log:
            with self.assertRaisesRegex(WorkerError, "deposits material"):
                audit_modifier_positive_e(
                    b"\n".join(interior), project, "bambustudio")
        message = "\n".join(log.output)
        self.assertIn("Bambu negative subtraction audit rejected G-code", message)
        self.assertIn("z_bands=", message)
        self.assertNotIn("X1", message)
        self.assertNotIn("Y1", message)
        self.assertNotIn("G1", message)

    def test_bambu_translated_negative_still_rejects_real_interiors(self):
        project = composite_fixture(negative=True)
        outside = [b"G90", b"M83", b"G0 X38 Y38 Z5"]
        outside.extend(
            ("G1 X%d Y%d E0.8" % (38 + i % 4, 38 + i % 4)).encode()
            for i in range(20))
        result = audit_modifier_positive_e(
            b"\n".join(outside), project, "bambustudio",
            translation_xy=(18.0, 18.0))
        self.assertEqual(result["modifier_region_paths"], [0])
        interior = [b"G90", b"M83", b"G0 X19 Y19 Z5"]
        interior.extend(
            (b"G1 X20 Y20 E0.5" if i % 2 == 0 else b"G1 X19 Y19 E0.5")
            for i in range(20))
        with self.assertRaisesRegex(WorkerError, "deposits material"):
            audit_modifier_positive_e(
                b"\n".join(interior), project, "bambustudio",
                translation_xy=(18.0, 18.0))
        with self.assertRaisesRegex(WorkerError, "Unverified"):
            audit_modifier_positive_e(
                b"\n".join(outside), project, "orcaslicer",
                translation_xy=(18.0, 18.0))

    def test_conical_negative_does_not_reject_material_outside_actual_cut(self):
        from slicer_worker.tests.test_modifier_3mf_validation import NS
        ns = "{" + NS + "}"
        with zipfile.ZipFile(io.BytesIO(composite_fixture(negative=True))) as archive:
            entries = {name: archive.read(name) for name in archive.namelist()}
        root = ET.fromstring(entries["3D/3dmodel.model"])
        mesh = root.find(ns + "resources/" + ns + "object[@id='4']/" + ns + "mesh")
        mesh.clear()
        vertices = ET.SubElement(mesh, ns + "vertices")
        faces = ET.SubElement(mesh, ns + "triangles")
        points = [(10 + 8 * math.cos(i * math.tau / 24),
                   10 + 8 * math.sin(i * math.tau / 24), 0)
                  for i in range(24)] + [(10, 10, 0), (10, 10, 20)]
        for x, y, z in points:
            ET.SubElement(vertices, ns + "vertex",
                          {"x": str(x), "y": str(y), "z": str(z)})
        for i in range(24):
            j = (i + 1) % 24
            for a, b, c in ((24, j, i), (i, j, 25)):
                ET.SubElement(faces, ns + "triangle",
                              {"v1": str(a), "v2": str(b), "v3": str(c)})
        entries["3D/3dmodel.model"] = ET.tostring(root)
        with io.BytesIO() as stream:
            with zipfile.ZipFile(stream, "w") as archive:
                for name, data in entries.items():
                    archive.writestr(name, data)
            project = stream.getvalue()

        # At Z=15 the cone radius is only 2 mm, despite its global
        # bounding box extending 8 mm. These paths are valid model walls.
        def program(y):
            return ("G90\nM83\nG0 X9 Y%s Z15\n" % y +
                    "".join("G1 X%s Y%s E0.5\n" % (11 if i % 2 == 0 else 9, y)
                            for i in range(20))).encode()
        self.assertEqual(audit_modifier_positive_e(
            program(15), project, "orcaslicer")["modifier_region_paths"], [0])
        # Actual interior deposition still fails, with the same mesh.
        with self.assertRaisesRegex(WorkerError, "deposits material"):
            audit_modifier_positive_e(program(10), project, "orcaslicer")

    def test_invalid_project_must_not_be_trusted(self):
        with self.assertRaises(WorkerError):
            modifier_bounds(b"not a valid 3MF", "orcaslicer")


if __name__ == "__main__":
    unittest.main()
