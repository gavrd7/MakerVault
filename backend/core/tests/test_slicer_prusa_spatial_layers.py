"""Prusa native multi-object layer audit: independently verify each mesh."""
from unittest import TestCase

from core.slicer_prusa_spatial_layers import audit_prusa_multi_object_layer_ranges
from core.tests.test_slicer_prusa_plate import cube, item


def plate():
    return [
        (item(x_mm=-35, variable_layer_profile={"version":1,"bands":[
            {"from_mm":5,"to_mm":15,"layer_mm":.12}]}), cube()),
        (item(x_mm=35), cube()),
    ]


def gcode(left=.12,right=.2):
    steps=[]
    for x,h in ((90,left),(160,right)):
        for n in range(1,int(20/h)):
            steps.append((round(n*h,5),x))
    steps.sort()
    lines=["M82","G92 E0"]
    for n,(z,x) in enumerate(steps,1):
        lines.extend([";LAYER_CHANGE",";Z:%.5f" % z,
                      "G0 X%d Y105" % x,"G1 X%d Y105 E%.4f" % (x+.4,n*.03)])
    return ("\n".join(lines)+"\n").encode()


class PrusaSpatialLayerTests(TestCase):
    def test_independent_z_schedule_matches_both_models(self):
        rows = audit_prusa_multi_object_layer_ranges(
            gcode(),plate(),bed_width=250,bed_depth=210,base_layer_mm=.2)
        self.assertEqual(len(rows),2)
        self.assertEqual([round(r["target_layer_mm"],2) for r in rows],[.12,.2])
        self.assertTrue(all(r["verified_steps"]>30 for r in rows))

    def test_adjacent_object_cannot_hide_ignored_variable_layer_change(self):
        with self.assertRaisesRegex(ValueError,"layer schedule"):
            audit_prusa_multi_object_layer_ranges(
                gcode(left=.2),plate(),bed_width=250,bed_depth=210,
                base_layer_mm=.2)

    def test_fifteen_objects_preserve_one_variable_band_and_fourteen_baselines(self):
        positions=[(x,y) for y in (-55,0,55)
                         for x in (-90,-45,0,45,90)]
        profile={"version":1,"bands":[
            {"from_mm":4,"to_mm":16,"layer_mm":.12}]}
        rows=[(item(x_mm=x,y_mm=y,
                    **({"variable_layer_profile":profile} if n==7 else {})),
               cube()) for n,(x,y) in enumerate(positions)]
        steps=[]
        for n,(x,y) in enumerate(positions):
            h=.12 if n==7 else .2
            for layer in range(1,int(20/h)):
                steps.append((round(layer*h,5),125+x,105+y))
        steps.sort()
        data=["M82","G92 E0"]
        for i,(z,x,y) in enumerate(steps,1):
            data.extend([f";Z:{z:.5f}",
                         f"G0 X{x} Y{y}",
                         f"G1 X{x+.3} Y{y} E{i*.03:.5f}"])
        proof=audit_prusa_multi_object_layer_ranges(
            ("\n".join(data)+"\n").encode(),rows,
            bed_width=250,bed_depth=210,base_layer_mm=.2)
        self.assertEqual(len(proof),15)
        self.assertEqual([round(r["target_layer_mm"],2) for r in proof],
                         [.12 if i==7 else .2 for i in range(15)])
        self.assertTrue(all(r["verified_steps"]>24 for r in proof))
        missing=[(dict(row),mesh) for row,mesh in rows]
        missing[7][0].pop("variable_layer_profile")
        with self.assertRaisesRegex(ValueError,"layer schedule"):
            audit_prusa_multi_object_layer_ranges(
                ("\n".join(data)+"\n").encode(),missing,
                bed_width=250,bed_depth=210,base_layer_mm=.2)

    def test_malformed_or_unrelated_output_rejected(self):
        for data in (b"none",b"G1 X500 Y500 E1",b"\xff",
                     gcode().replace(b"E0.0300", b"E1e309")):
            with self.subTest(data=data),self.assertRaises(ValueError):
                audit_prusa_multi_object_layer_ranges(
                    data,plate(),bed_width=250,bed_depth=210,base_layer_mm=.2)
