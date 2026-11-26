"""Prusa MMU/XL audit rejects wrong model material even with valid T changes."""
from unittest import TestCase

from core.slicer_prusa_native_tools import audit_prusa_native_object_tools
from core.tests.test_slicer_prusa_plate import item, cube


def models():
    return [(item(x_mm=-35),cube()),(item(x_mm=35),cube())]


def sample(*, swap=False, missing=False, contamination=0):
    lines=["M82","G92 E0","T0"]
    count=0
    for t,x in ((0,90),(1,160)):
        lines.append("T%d" % t)
        for i in range(60):
            count+=1
            current=1-t if swap else t
            if i<contamination:
                current=1-t
            if not missing:
                lines.append("T%d" % current)
            lines.append("G1 X%.3f Y105 E%.4f" % (x+i*.001,count*.03))
    return ("\n".join(lines)+"\n").encode()


class PrusaToolAuditTests(TestCase):
    def test_distinct_model_tools_are_real_extrusion_not_header_selection(self):
        good=audit_prusa_native_object_tools(sample(),models(),[0,1],
             bed_width=250,bed_depth=210)
        self.assertEqual(good["correct_deposition_moves"],[59,59])
        self.assertEqual(good["incorrect_deposition_moves"],[0,0])

    def test_incorrect_tool_assignments_and_contamination_rejected(self):
        for data in (sample(swap=True),sample(contamination=15),
                     sample().replace(b"T1",b"T5"),b"T0\nT1\n"):
            with self.subTest(data=data[:35]), self.assertRaises(ValueError):
                audit_prusa_native_object_tools(data,models(),[0,1],
                     bed_width=250,bed_depth=210)

    def test_invalid_tool_contracts_rejected(self):
        for assignments in ([0,0],[0,5],[-1,1],[0],["0",1]):
            with self.subTest(assignments=assignments),self.assertRaises(ValueError):
                audit_prusa_native_object_tools(sample(),models(),assignments,
                     bed_width=250,bed_depth=210)

    def test_stationary_extrusion_does_not_prove_model_tool(self):
        stationary=sample().replace(b"G1 X",b"G0 X")
        with self.assertRaisesRegex(ValueError,"did not prove"):
            audit_prusa_native_object_tools(
                stationary,models(),[0,1],bed_width=250,bed_depth=210)

    def test_absolute_e_with_relative_xy_is_a_valid_deposited_toolpath(self):
        lines=["M83","G90","T0","G0 X90 Y105","G91"]
        lines.extend(["G1 X.05 Y0 E.03"]*60)
        lines.extend(["G90","T1","G0 X160 Y105","G91"])
        lines.extend(["G1 X.05 Y0 E.03"]*60)
        output=("\n".join(lines)+"\n").encode()
        result=audit_prusa_native_object_tools(
            output,models(),[0,1],bed_width=250,bed_depth=210)
        self.assertEqual(result["correct_deposition_moves"],[60,60])

    def test_crossing_into_a_model_is_not_proof_of_internal_deposition(self):
        lines=["M83","G90","T0"]
        for _ in range(60):
            lines.extend(["G0 X70 Y105","G1 X90 Y105 E.03"])
        lines.extend(["T1","G0 X160 Y105"])
        lines.extend(["G1 X%.2f Y105 E.03" % (160+.05*i)
                      for i in range(60)])
        with self.assertRaisesRegex(ValueError,"did not prove"):
            audit_prusa_native_object_tools(
                ("\n".join(lines)+"\n").encode(),models(),[0,1],
                bed_width=250,bed_depth=210)
