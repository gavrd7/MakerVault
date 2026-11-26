from unittest import TestCase

from core.slicer_prusa_colour_audit import audit_prusa_painted_wall_tools


def sample(*, painted=True, leaked=False, wrong_tool=False):
    lines=["M83",";TYPE:External perimeter"]
    for tool,region in ((1,"painted"),(0,"unpainted")):
        lines.append("T"+str(tool if not wrong_tool else 0))
        y=95 if region=="painted" else 115
        for n in range(25):
            lines.append("G1 X%s Y%s E0.03" % (115+n*0.5,y))
    if leaked:
        lines.append("T1")
        lines.extend("G1 X%.1f Y115 E0.02" % (120+n*.5) for n in range(5))
    if not painted:
        lines=[line for line in lines if line!="T1"]
    return ("\n".join(lines)+"\n").encode()


class PrusaColourAuditTests(TestCase):
    def audit(self,data,**kwargs):
        return audit_prusa_painted_wall_tools(
            data,painted_wall=(114,136,93,97),
            unpainted_wall=(114,136,113,117),**kwargs)

    def test_positive_native_tool_regions(self):
        result=self.audit(sample())
        self.assertEqual(result[1]["painted"],24)
        self.assertEqual(result[0]["unpainted"],24)

    def test_missing_painted_material_and_wrong_side_rejected(self):
        for gcode in (sample(wrong_tool=True),sample(leaked=True)):
            with self.subTest(gcode=gcode[:40]),self.assertRaises(ValueError):
                self.audit(gcode)

    def test_invalid_regions_or_threshold(self):
        for bad in ((114,136,93,97),(114,114,93,97),(1,float("nan"),2,3)):
            with self.assertRaises(ValueError):
                audit_prusa_painted_wall_tools(
                    sample(),painted_wall=(114,136,93,97),
                    unpainted_wall=bad)
        with self.assertRaises(ValueError):
            self.audit(sample(),minimum_moves=True)

    def test_stationary_priming_does_not_count_as_painted_wall(self):
        original=sample()
        # Replace the T1 wall passes with travel followed by unmoving E.
        raw=original.replace(b"G1 X", b"G0 X")
        with self.assertRaisesRegex(ValueError,"did not produce isolated"):
            self.audit(raw)

    def test_relative_xy_and_relative_e_painted_wall_segments(self):
        lines=["G90","M83","T1",";TYPE:External perimeter",
               "G0 X115 Y95","G91"]
        lines.extend(["G1 X0.5 Y0 E0.03"]*25)
        lines.extend(["G90","T0","G0 X115 Y115","G91"])
        lines.extend(["G1 X0.5 Y0 E0.03"]*25)
        result=self.audit(("\\n".join(lines)+"\\n").encode())
        self.assertEqual(result[1]["painted"],25)
        self.assertEqual(result[0]["unpainted"],25)

    def test_extrusion_crossing_region_does_not_qualify_wall(self):
        lines=["G90","M83","T1",";TYPE:External perimeter"]
        for n in range(25):
            lines.extend(["G0 X110 Y95","G1 X120 Y95 E0.03"])
        lines.extend(["T0","G0 X115 Y115"])
        lines.extend(["G1 X%.2f Y115 E0.03" % (115+n*.5) for n in range(25)])
        with self.assertRaisesRegex(ValueError,"did not produce isolated"):
            self.audit(("\\n".join(lines)+"\\n").encode())
