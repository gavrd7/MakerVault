"""Real extrusion roles, not imported paint tags, qualify Prusa fuzzy skin."""
from unittest import TestCase

from core.slicer_prusa_fuzzy_audit import audit_prusa_two_object_fuzzy
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
