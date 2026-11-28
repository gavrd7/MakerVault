"""Real extrusion roles, not imported paint tags, qualify Prusa fuzzy skin."""
from unittest import TestCase

from core.slicer_prusa_fuzzy_audit import (audit_prusa_two_object_fuzzy,
    audit_prusa_multi_object_fuzzy)
from core.tests.test_slicer_prusa_plate import cube, item


def models():
    painted={"version":2,"signature":"12:deadbeef","regions":[{
        "slot":0,"patches":[{"face":0,"polygon":[[0,0,0],[1,0,0],[0,1,0]]}]}]}
    return [(item(x_mm=-35,fuzzy_skin_paint=painted),cube()),
            (item(x_mm=35),cube())]


def gcode(*, paint=True, leak=False):
    lines=["M82","G92 E0"]
    extrusion=0.
    for i in range(120):
        z=4+i*.1
        lines.extend([";LAYER_CHANGE",";TYPE:External perimeter",
                      "G0 X85 Y95 Z%.3f" % z])
        extrusion+=.025
        end=85.3 if paint else 95
        lines.append("G1 X%.3f Y95 E%.5f" % (end,extrusion))
        lines.append("G0 X155 Y95")
        extrusion+=.025
        other=155.3 if leak else 165
        lines.append("G1 X%.3f Y95 E%.5f" % (other,extrusion))
    return ("\n".join(lines)+"\n").encode()


class PrusaTwoObjectFuzzyAuditTests(TestCase):
    def test_painted_and_unpainted_models_are_independently_measured(self):
        result=audit_prusa_two_object_fuzzy(gcode(),models(),
                                            bed_width=250,bed_depth=210)
        self.assertEqual(result["painted_short_external_moves"],120)
        self.assertEqual(result["unpainted_short_external_moves"],0)

    def test_native_toolpath_missing_or_spilling_texture_is_rejected(self):
        for raw in (gcode(paint=False),gcode(leak=True),b"broken",b"\xff"):
            with self.subTest(length=len(raw)),self.assertRaises(ValueError):
                audit_prusa_two_object_fuzzy(raw,models(),
                                             bed_width=250,bed_depth=210)

    def test_mixed_paint_or_ambiguous_models_refused(self):
        row=models()
        both=[row[0],({**row[1][0],
                      "fuzzy_skin_paint":row[0][0]["fuzzy_skin_paint"]},row[1][1])]
        with self.assertRaises(ValueError):
            audit_prusa_two_object_fuzzy(gcode(),both,
                                         bed_width=250,bed_depth=210)

    def test_relative_xyz_tracks_short_deposited_wall_segments(self):
        lines=["M82","G92 E0"]
        e=0.
        for i in range(120):
            z=4+i*.1
            lines.extend([";TYPE:External perimeter",
                          "G90","G0 X85 Y95 Z%.3f" % z,"G91"])
            e+=.025
            lines.append("G1 X.3 Y0 E%.5f" % e)
            lines.extend(["G90","G0 X155 Y95","G91"])
            e+=.025
            lines.append("G1 X10 Y0 E%.5f" % e)
        result=audit_prusa_two_object_fuzzy(
            ("\n".join(lines)+"\n").encode(),models(),
            bed_width=250,bed_depth=210)
        self.assertEqual(result["painted_short_external_moves"],120)
        self.assertEqual(result["unpainted_short_external_moves"],0)

    def test_fifteen_model_fuzzy_is_isolated_to_selected_model(self):
        painted=models()[0][0]["fuzzy_skin_paint"]
        positions=[(x,y) for y in (-55,0,55)
                         for x in (-90,-45,0,45,90)]
        sources=[(item(x_mm=x,y_mm=y,
                       **({"fuzzy_skin_paint":painted} if n==7 else {})),
                  cube())
                 for n,(x,y) in enumerate(positions)]
        lines=["M83","G90",";TYPE:External perimeter"]
        for n in range(120):
            z=4+n*.1
            lines.extend([f"G0 X125 Y95 Z{z:.3f}",
                          f"G1 X{125.3+n*.00001:.4f} Y95 E.03"])
        gcode=("\n".join(lines)+"\n").encode()
        result=audit_prusa_multi_object_fuzzy(
            gcode,sources,bed_width=250,bed_depth=210)
        self.assertEqual(result["painted_model_index"],7)
        self.assertEqual(result["painted_short_external_moves"],120)
        self.assertEqual(result["unpainted_short_external_moves"],0)
        self.assertEqual(len(result["per_model_short_external_moves"]),15)
        # Real moving external-wall extrusion inside a different model's
        # footprint must not be mistaken for harmless stationary E recovery.
        leaked=(gcode+b"G0 X80 Y40 Z6\n"+
                b"".join(f"G1 X{80+.03*i:.2f} Y40 E.03\n".encode()
                         for i in range(1,12)))
        with self.assertRaisesRegex(ValueError,"not isolated"):
            audit_prusa_multi_object_fuzzy(
                leaked,sources,bed_width=250,bed_depth=210)
        with self.assertRaises(ValueError):
            audit_prusa_multi_object_fuzzy(
                gcode,sources+[sources[0]]*186,
                bed_width=250,bed_depth=210)

    def test_two_independent_fuzzy_models_on_fifteen_instance_plate(self):
        painted=models()[0][0]["fuzzy_skin_paint"]
        positions=[(x,y) for y in (-55,0,55)
                         for x in (-90,-45,0,45,90)]
        sources=[(item(x_mm=x,y_mm=y,
                       **({"fuzzy_skin_paint":painted} if n in (7,8) else {})),
                  cube())
                 for n,(x,y) in enumerate(positions)]
        lines=["M83","G90",";TYPE:External perimeter"]
        for n in range(120):
            z=4+n*.1
            for center in (125,170):
                lines.extend([f"G0 X{center} Y95 Z{z:.3f}",
                              f"G1 X{center+.3:.3f} Y95 E.03"])
        output=("\n".join(lines)+"\n").encode()
        passed=audit_prusa_multi_object_fuzzy(
            output,sources,bed_width=250,bed_depth=210)
        self.assertEqual(passed["painted_model_indices"],[7,8])
        self.assertEqual(passed["painted_short_external_moves"],240)
        self.assertEqual(passed["unpainted_short_external_moves"],0)
        wrong=[(dict(row),mesh) for row,mesh in sources]
        wrong[8][0].pop("fuzzy_skin_paint")
        with self.assertRaisesRegex(ValueError,"not isolated"):
            audit_prusa_multi_object_fuzzy(
                output,wrong,bed_width=250,bed_depth=210)

    def test_non_external_wall_roles_cannot_qualify_fuzzy_skin(self):
        raw=gcode().replace(b";TYPE:External perimeter",
                            b";TYPE:Unsupported external perimeter")
        with self.assertRaisesRegex(ValueError,"not isolated"):
            audit_prusa_two_object_fuzzy(
                raw,models(),bed_width=250,bed_depth=210)
