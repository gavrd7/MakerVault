"""Two-object Prusa painted support cannot be approved by stationary E recovery."""
from unittest import TestCase

from core.slicer_prusa_support_audit import (
    audit_prusa_two_object_support, validate_prusa_two_support_plate,
    audit_prusa_multi_object_support, validate_prusa_multi_support_plate,
)
from core.tests.test_slicer_prusa_plate import item, cube


def sources(*, paint=0):
    region = {"regions": [{"slot": 0, "patches": [
        {"face": 0, "polygon": [[0, 0, 0], [1, 0, 0], [0, 1, 0]]}
    ]}]}
    return [(
        item(x_mm=x, **({"support_paint": region} if paint == i else {})),
        cube(),
    ) for i, x in enumerate((-35, 35))]


def native_paths(*, painted=0, leak=0, stationary=59, relative=False):
    """Two physically disjoint cubes, 60 genuinely deposited painted segments."""
    left, right = 90, 160
    base = left if painted == 0 else right
    other = right if painted == 0 else left
    lines = ["G90", "M83", ";TYPE:Support material", f"G0 X{base} Y105"]
    if relative:
        lines.append("G91")
        lines.extend(["G1 X0.05 Y0 E0.03"] * 60)
        lines.append("G90")
    else:
        lines.extend([f"G1 X{base + .05*(i+1):.3f} Y105 E0.03" for i in range(60)])
    lines.append(f"G0 X{other} Y105")
    # The historical neighbour 'leak' consisted of exactly this kind of
    # stationary E recovery: it is deliberately not support deposition.
    lines.extend(["G1 E0.03"] * stationary)
    if leak:
        lines.extend([f"G1 X{other + .05*(i+1):.3f} Y105 E0.03" for i in range(leak)])
    return ("\n".join(lines) + "\n").encode("utf-8")


class PrusaTwoObjectSupportTests(TestCase):
    def audit(self, data, *, painted=0):
        return audit_prusa_two_object_support(
            data, sources(paint=painted), bed_width=250, bed_depth=210)

    def test_both_directions_ignore_59_stationary_recovery_events(self):
        for i in (0, 1):
            with self.subTest(painted=i):
                result = self.audit(native_paths(painted=i), painted=i)
                self.assertEqual(result["painted_model_index"], i)
                self.assertEqual(result["painted_support_moves"], 60)
                self.assertEqual(result["unpainted_support_moves"], 0)
                self.assertEqual(result["stationary_recovery_moves"][1-i], 59)

    def test_small_native_support_paths_are_not_artificially_rejected(self):
        data = (b"G90\nM83\n;TYPE:Support material\n"
                b"G0 X90 Y105\nG1 X90.5 Y105 E.02\nG1 X91 Y105 E.03\n"
                b"G0 X160 Y105\nG1 E.08\n")
        result = self.audit(data)
        self.assertEqual(result["painted_support_moves"], 2)
        self.assertEqual(result["painted_support_e_mm"], .05)
        self.assertEqual(result["unpainted_support_moves"], 0)
        with self.assertRaisesRegex(ValueError, "not isolated"):
            self.audit(data.replace(b"G1 X91 Y105 E.03", b"G0 X91 Y105"))

    def test_relative_xy_and_e_are_genuinely_deposited(self):
        result = self.audit(native_paths(relative=True))
        self.assertEqual(result["painted_support_moves"], 60)

    def test_genuine_neighbour_support_leakage_is_refused(self):
        with self.assertRaisesRegex(ValueError, "not isolated"):
            self.audit(native_paths(leak=1))
        with self.assertRaisesRegex(ValueError, "not isolated"):
            self.audit(native_paths(stationary=0, leak=8))

    def test_missing_paths_and_forged_role_cannot_pass(self):
        for raw in (native_paths().replace(b"G1 X", b"G0 X"),
                    native_paths().replace(b";TYPE:Support material",
                                           b";TYPE:Unsupported material"),
                    b"\xff"):
            with self.subTest(raw=raw[:30]), self.assertRaises(ValueError):
                self.audit(raw)

    def test_ambiguous_or_combined_plate_is_rejected(self):
        items = [row for row, _ in sources()]
        self.assertEqual(validate_prusa_two_support_plate(items), 0)
        with self.assertRaises(ValueError):
            validate_prusa_two_support_plate([{**items[0], "support_paint": {}},
                                               items[1]])
        with self.assertRaises(ValueError):
            validate_prusa_two_support_plate([items[0],
                {**items[1], "support_paint": items[0]["support_paint"]}])
        for forbidden in ({"process_overrides": {"wall_loops": 4}},
                          {"modifier_volumes": [{"id": "unqualified"}]},
                          {"rotation_deg": 90},
                          {"scale_percent": 120},
                          {"seam_paint": {"regions": [{"slot": 0}]}}):
            with self.subTest(forbidden=forbidden), self.assertRaises(ValueError):
                validate_prusa_two_support_plate([items[0], {**items[1], **forbidden}])
        placed = sources()
        placed[1] = (item(x_mm=-34), cube())
        with self.assertRaisesRegex(ValueError, "overlap"):
            audit_prusa_two_object_support(
                native_paths(), placed, bed_width=250, bed_depth=210)


class PrusaMultiObjectSupportTests(TestCase):
    def models(self, painted=1):
        example = sources(paint=0)[0][0]["support_paint"]
        return [(item(x_mm=x, **({"support_paint": example}
                                  if n == painted else {})), cube())
                for n, x in enumerate((-55, 0, 55))]

    def gcode(self, painted=1, leaked=None):
        centers = (70, 125, 180)
        lines = ["G90", "M83", ";TYPE:Support material",
                 f"G0 X{centers[painted]} Y105"]
        lines.extend(
            f"G1 X{centers[painted]+.05*(n+1):.3f} Y105 E.03"
            for n in range(60))
        for other in range(3):
            if other == painted:
                continue
            lines.append(f"G0 X{centers[other]} Y105")
            lines.extend(["G1 E.03"]*20)
            if other == leaked:
                lines.append(f"G1 X{centers[other]+.3} Y105 E.03")
        return ("\n".join(lines)+"\n").encode()

    def test_three_disjoint_models_only_one_support_enforcer(self):
        for painted in range(3):
            with self.subTest(painted=painted):
                rows = self.models(painted)
                self.assertEqual(validate_prusa_multi_support_plate(
                    [r for r,_ in rows]), painted)
                out = audit_prusa_multi_object_support(
                    self.gcode(painted), rows, bed_width=250, bed_depth=210)
                self.assertEqual(out["painted_model_index"], painted)
                self.assertEqual(out["painted_support_moves"],60)
                self.assertEqual(out["unpainted_support_moves"],0)
                self.assertEqual(sum(out["stationary_recovery_moves"]),40)
                with self.assertRaisesRegex(ValueError, "not isolated"):
                    audit_prusa_multi_object_support(
                        self.gcode(painted, leaked=(painted+1)%3),
                        rows, bed_width=250, bed_depth=210)
                with self.assertRaises(ValueError):
                    audit_prusa_two_object_support(
                        self.gcode(painted), rows,
                        bed_width=250, bed_depth=210)

    def test_multi_object_support_scope_rejects_ambiguous_plates(self):
        plain = self.models()
        with self.assertRaises(ValueError):
            validate_prusa_multi_support_plate(
                [r for r,_ in plain[:1]])
        with self.assertRaises(ValueError):
            validate_prusa_multi_support_plate(
                [r for r,_ in plain]*5)
        twice = self.models()
        twice[0][0]["support_paint"] = twice[1][0]["support_paint"]
        with self.assertRaises(ValueError):
            validate_prusa_multi_support_plate([r for r,_ in twice])
        crowded = self.models()
        crowded[2] = (item(x_mm=1), cube())
        with self.assertRaisesRegex(ValueError, "overlap"):
            audit_prusa_multi_object_support(
                self.gcode(), crowded, bed_width=250, bed_depth=210)
