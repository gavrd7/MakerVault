"""Prusa 2.9.7 native tower placement is project metadata, not an INI override."""
import io
from unittest import TestCase
import zipfile
from defusedxml import ElementTree as SafeET

from core.slicer_prusa_wipe_tower import (
    add_prusa_native_wipe_tower, PART,
)
from core.slicer_prusa_3mf import build_prusa_native_3mf
from core.tests.test_slicer_prusa_plate import cube, item
from core.slicer_profiles import SlicerProfileError


class PrusaWipeTowerMetadataTests(TestCase):
    def source(self):
        return build_prusa_native_3mf([(item(),cube())],
                                       bed_width=250,bed_depth=210)

    def test_prusa_per_bed_tower_coordinates_are_preserved(self):
        base=self.source()
        for x in (35,165):
            with self.subTest(x=x):
                result=add_prusa_native_wipe_tower(
                    base,x_mm=x,y_mm=145,rotation_deg=0,
                    bed_width=250,bed_depth=210)
                with zipfile.ZipFile(io.BytesIO(result)) as parts:
                    self.assertEqual(parts.namelist().count(PART),1)
                    xml=SafeET.fromstring(parts.read(PART))
                self.assertEqual(xml.tag,"wipe_tower_information")
                self.assertEqual(xml.attrib,{"bed_idx":"0",
                    "position_x":f"{x:.3f}","position_y":"145.000",
                    "rotation_deg":"0.000"})
                with zipfile.ZipFile(io.BytesIO(base)) as original:
                    with zipfile.ZipFile(io.BytesIO(result)) as updated:
                        for name in original.namelist():
                            self.assertEqual(original.read(name),updated.read(name))

    def test_invalid_and_ambiguous_towers_fail_closed(self):
        source=self.source()
        for kwargs in (
            {"x_mm":-1,"y_mm":145,"rotation_deg":0},
            {"x_mm":180,"y_mm":145,"rotation_deg":0},
            {"x_mm":35,"y_mm":175,"rotation_deg":0},
            {"x_mm":35,"y_mm":145,"rotation_deg":float("nan")},
            {"x_mm":True,"y_mm":145,"rotation_deg":0},
        ):
            with self.subTest(kwargs=kwargs),self.assertRaises(SlicerProfileError):
                add_prusa_native_wipe_tower(
                    source,bed_width=250,bed_depth=210,**kwargs)
        # Repeated per-bed origin cannot be silently installed into a project.
        already=add_prusa_native_wipe_tower(source,x_mm=35,y_mm=145,
                              rotation_deg=0,bed_width=250,bed_depth=210)
        with self.assertRaises(SlicerProfileError):
            add_prusa_native_wipe_tower(already,x_mm=80,y_mm=145,
                        rotation_deg=0,bed_width=250,bed_depth=210)
