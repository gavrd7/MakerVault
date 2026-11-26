"""Prusa semantic seam audit checks actual G-code, not only 3MF attributes."""
import unittest

from core.slicer_prusa_seam_audit import (\n    audit_prusa_seam_enforcer_gcode, validate_prusa_front_seam_candidate,\n)\nfrom core.slicer_prusa_3mf import validate_prusa_project_admission\nfrom scripts.prusa_generate_mmu_paint import fixture


def project():
    return {
        "x_mm": 0, "y_mm": 0, "z_mm": 0, "rotation_deg": 0,
        "scale_percent": 100,
        "seam_paint": {"regions": [{"slot": 0, "patches": [{
            "face": 5,
            "polygon": [[10, -10, 0], [10, 10, 0], [10, 10, 20]],
        }]}]},
    }


def gcode(*, right=True, relative=False):
    lines = ["M83" if relative else "M82", "G92 E0"]
    e = 0
    for layer in range(1, 13):
        x = 134.78 if right else 115.22
        z = round(layer*.2+2, 3)
        lines.extend([";LAYER_CHANGE", "G0 Z" + str(z),
                      ";TYPE:External perimeter"])
        e = 1 if relative else e+1
        lines.append("G1 X%.2f Y114.78 E%.3f" % (x, e))
        lines.append("G0 X120 Y100")
    return ("\n".join(lines)+"\n").encode()


class PrusaFrontSeamWorkBenchGateTests(unittest.TestCase):
    def front(self):
        _stl, _mesh, _tags, paint = fixture(include_paint=True)
        # The established native research fixture covers both complete
        # front wall triangles of a grounded 20mm Prusa cube.
        paint["regions"][0]["slot"] = 0
        paint.pop("palette", None)
        return {
            "asset_id": "front-seam-model",
            "x_mm": 0, "y_mm": 0, "z_mm": 0,
            "rotation_deg": 0, "scale_percent": 100,
            "seam_paint": paint,
        }

    def test_only_proven_prusa_front_enforcer_is_admitted(self):
        row = self.front()
        self.assertEqual(validate_prusa_front_seam_candidate(row)["version"], 2)
        self.assertFalse(validate_prusa_project_admission([row], {}, "2.9.7"))

    def test_unqualified_seam_face_or_combination_is_rejected(self):
        for change in (
            {"rotation_deg": 90},
            {"z_mm": 1},
            {"scale_percent": 120},
            {"process_overrides": {"wall_loops": 4}},
            {"support_paint": {"regions": [{"slot": 0}]}},
            {"modifier_volumes": [{"id": "new-volume"}]},
        ):
            with self.subTest(change=change),self.assertRaises(ValueError):
                validate_prusa_front_seam_candidate({**self.front(),**change})
        for bad in ("right", "back"):
            with self.subTest(direction=bad):
                row=self.front()
                polygon=row["seam_paint"]["regions"][0]["patches"][0]["polygon"]
                for p in polygon:
                    if bad=="right":
                        p[1]=0
                    else:
                        p[1]=10
                with self.assertRaises(ValueError):
                    validate_prusa_front_seam_candidate(row)
        with self.assertRaises(ValueError):
            validate_prusa_project_admission([self.front(), self.front()], {}, "2.9.7")

class PrusaSeamAuditTests(unittest.TestCase):
    def test_painted_face_is_supported_by_measured_starts(self):
        for relative in (True, False):
            with self.subTest(relative=relative):
                result = audit_prusa_seam_enforcer_gcode(
                    gcode(relative=relative), project(), bed_width=250, bed_depth=210)
                self.assertEqual(result["matching_layers"], 12)

    def test_unpainted_opposite_wall_and_non_extruding_comments_rejected(self):
        for raw in (gcode(right=False), gcode().replace(b"Y114.78 E", b"Y114.78 F"),
                    b";TYPE:External perimeter\n;LAYER_CHANGE\n"*10):
            with self.subTest(length=len(raw)), self.assertRaises(ValueError):
                audit_prusa_seam_enforcer_gcode(raw, project(), bed_width=250, bed_depth=210)

    def test_unsupported_patches_and_transforms_refused(self):
        for invalid in (
            {"rotation_deg": 90},
            {"scale_percent": 150},
            {"seam_paint": {"regions": [{"slot": 1, "patches": project()["seam_paint"]["regions"][0]["patches"]}]}},
        ):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                audit_prusa_seam_enforcer_gcode(
                    gcode(), {**project(), **invalid}, bed_width=250, bed_depth=210)
