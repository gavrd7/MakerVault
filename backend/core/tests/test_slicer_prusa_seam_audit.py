"""Prusa semantic seam audit checks actual G-code, not only 3MF attributes."""
import unittest

from core.slicer_prusa_seam_audit import (
    audit_prusa_seam_enforcer_gcode, audit_prusa_multi_object_seam_gcode,
    validate_prusa_front_seam_candidate,
)
from core.slicer_prusa_3mf import validate_prusa_project_admission
from scripts.prusa_generate_mmu_paint import fixture


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
    lines = ["M83" if relative else "M82", "G92 E0", "G0 X120 Y100"]
    e = 0
    for layer in range(1, 13):
        x = 134.78 if right else 115.22
        z = round(layer*.2+2, 3)
        lines.extend([";LAYER_CHANGE", "G0 Z" + str(z),
                      ";TYPE:External perimeter"])
        e = 1 if relative else e+1
        lines.append("G0 X%.2f Y114.78" % (x-.25))
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

    def test_multi_object_seam_audits_each_selected_model_not_first_plate_wall(self):
        mesh,*_=fixture(include_paint=True)
        models=[]
        for index,(x,y) in enumerate(
                (point for ypos in (-55,0,55)
                 for point in ((x,ypos) for x in (-90,-45,0,45,90)))):
            item={"asset_id":f"seam-{index}","x_mm":x,"y_mm":y,
                  "z_mm":0,"rotation_deg":0,"scale_percent":100}
            if index in (7,8):
                item["seam_paint"]=self.front()["seam_paint"]
            models.append((item,mesh))
        self.assertFalse(validate_prusa_project_admission(
            [item for item,_ in models],{},"2.9.7"))
        def output(second_wrong=False):
            lines=["M83","G90"]
            for layer in range(1,14):
                lines.append(";LAYER_CHANGE")
                for index in (7,8):
                    cx=125+models[index][0]["x_mm"]
                    cy=105+models[index][0]["y_mm"]
                    y=cy+(9.78 if second_wrong and index==8 else -9.78)
                    lines.extend([f"G0 X{cx-9.78:.2f} Y{y:.2f} Z{layer+.5:.2f}",
                                  ";TYPE:External perimeter",
                                  f"G1 X{cx-9.48:.2f} Y{y:.2f} E.03"])
            return ("\n".join(lines)+"\n").encode()
        approved=audit_prusa_multi_object_seam_gcode(
            output(),models,bed_width=250,bed_depth=210)
        self.assertEqual(approved["painted_model_indices"],[7,8])
        self.assertEqual(approved["sampled_layers"],{7:13,8:13})
        self.assertEqual(approved["matching_layers"],{7:13,8:13})
        with self.assertRaisesRegex(ValueError,"selected face"):
            audit_prusa_multi_object_seam_gcode(
                output(second_wrong=True),models,bed_width=250,bed_depth=210)
        with self.assertRaises(ValueError):
            audit_prusa_multi_object_seam_gcode(
                output(),models+[models[0]]*186,
                bed_width=250,bed_depth=210)

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
        # The native project dialect supports per-object seam metadata.
        # Independent G-code admission (not the 3MF serializer) rejects
        # ambiguous overlapping source footprints.
        self.assertFalse(validate_prusa_project_admission(
            [self.front(),self.front()],{},"2.9.7"))

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

    def test_stationary_extrusion_cannot_satisfy_seam_audit(self):
        raw = gcode()
        # Priming in place is not a measured first-wall start even when
        # the current role and location happen to match the painted face.
        raw = raw.replace(b"G1 X134.78 Y114.78 E", b"G0 X134.78 Y114.78\nG1 E")
        with self.assertRaisesRegex(ValueError, "did not follow"):
            audit_prusa_seam_enforcer_gcode(raw, project(), bed_width=250, bed_depth=210)

    def test_relative_xy_perimeter_starts_are_measured(self):
        raw = gcode()
        # Fixture uses absolute XY. Explicitly entering G91 makes identical
        # coordinates into displacements; the candidate must fail closed.
        raw = raw.replace(b";TYPE:External perimeter", b"G91\n;TYPE:External perimeter")
        with self.assertRaises(ValueError):
            audit_prusa_seam_enforcer_gcode(raw, project(), bed_width=250, bed_depth=210)

    def test_research_modes_preserve_native_preset_except_seam_position(self):
        from scripts.prusa_native_seam_acceptance import override_research_seam_position
        raw=b"layer_height = 0.2\nseam_position = rear\nperimeters = 3\n"
        self.assertEqual(override_research_seam_position(raw, None),raw)
        for mode in ("aligned","nearest","random","rear"):
            result=override_research_seam_position(raw,mode)
            self.assertIn(b"layer_height = 0.2\n",result)
            self.assertIn(b"perimeters = 3\n",result)
            self.assertEqual(result.count(b"seam_position ="),1)
            self.assertIn(b"seam_position = "+mode.encode(),result)
        with self.assertRaises(ValueError):
            override_research_seam_position(raw,"not-a-native-mode")


class PrusaFourFaceSeamQualificationTests(unittest.TestCase):
    def test_four_independently_fingerprinted_vertical_directions_roundtrip(self):
        import json
        from pathlib import Path
        from tempfile import TemporaryDirectory
        from scripts.prusa_generate_paint_fixtures import main as generate
        from core.slicer_prusa_seam_audit import prusa_qualified_seam_direction
        from slicer_worker.prusa_3mf_validation import validate_prusa_native_3mf

        with TemporaryDirectory(prefix="prusa-directions-") as root:
            generate(root)
            for face in ("front", "back", "left", "right"):
                with self.subTest(face=face):
                    item = json.loads((Path(root)/("seam-"+face+".json")).read_text())
                    selected, direction = prusa_qualified_seam_direction(item)
                    self.assertEqual(direction, face)
                    self.assertEqual(selected["version"], 2)
                    self.assertFalse(validate_prusa_project_admission(
                        [item], {}, "2.9.7"))
                    receipt = validate_prusa_native_3mf(
                        (Path(root)/("seam-"+face+".3mf")).read_bytes())
                    self.assertIn("slic3rpe:SeamPaintingVersion",
                                  receipt["paint_channels"])
                    if face != "front":
                        with self.assertRaises(ValueError):
                            validate_prusa_front_seam_candidate(item)

    def test_selected_vertical_face_has_deposited_first_wall_starts(self):
        from pathlib import Path
        from tempfile import TemporaryDirectory
        import json
        from scripts.prusa_generate_paint_fixtures import main as generate
        from core.slicer_prusa_seam_audit import prusa_qualified_seam_direction

        with TemporaryDirectory(prefix="prusa-direction-wall-") as root:
            generate(root)
            for face in ("front", "back", "left", "right"):
                with self.subTest(face=face):
                    item = json.loads((Path(root)/("seam-"+face+".json")).read_text())
                    _, direction = prusa_qualified_seam_direction(item)
                    self.assertEqual(direction, face)
                    xy = {"front": (125, 95.22), "back": (125, 114.78),
                          "left": (115.22, 105), "right": (134.78, 105)}
                    x, y = xy[face]
                    lines = ["M82", "G92 E0", "G0 X120 Y100"]
                    e = 0
                    for layer in range(1, 13):
                        z = round(2+layer*.2, 3)
                        lines.extend([";LAYER_CHANGE", "G0 Z" + str(z),
                                      ";TYPE:External perimeter"])
                        e += 1
                        start_x = x-.25 if face in ("front", "back") else x
                        start_y = y-.25 if face in ("left", "right") else y
                        lines.append("G0 X%.2f Y%.2f" % (start_x, start_y))
                        lines.append("G1 X%.2f Y%.2f E%.3f" % (x, y, e))
                        lines.append("G0 X120 Y100")
                    raw = ("\n".join(lines)+"\n").encode()
                    observed = audit_prusa_seam_enforcer_gcode(
                        raw, item, bed_width=250, bed_depth=210)
                    self.assertEqual(observed["matching_layers"], 12)

    def test_random_native_seam_process_is_temporary_and_bounded(self):
        from core.slicer_prusa_process_settings import qualify_prusa_seam_process
        from core.slicer_prusa_native_resolution import parse_prusa_profile
        source = b"layer_height = .2\nseam_position = rear\n"
        modified = qualify_prusa_seam_process(source, "random")
        self.assertEqual(parse_prusa_profile(modified, "process")["seam_position"],
                         "random")
        self.assertIn(b"seam_position = rear", source)
        with self.assertRaises(ValueError):
            qualify_prusa_seam_process(source, "nearest")

    def test_first_wall_endpoint_inside_but_start_outside_is_rejected(self):
        raw = gcode().replace(b"G0 X134.53 Y114.78", b"G0 X120 Y100")
        with self.assertRaisesRegex(ValueError, "did not follow"):
            audit_prusa_seam_enforcer_gcode(
                raw, project(), bed_width=250, bed_depth=210)
