"""Research-only native Prusa SupportBlocker volume geometry contracts.

These assertions do not qualify production two-object support painting:
the actual 2.9.7 CLI must prove suppression of neighbour support moves.
"""
import io
import unittest
import zipfile
from defusedxml import ElementTree as SafeET

from core.slicer_prusa_3mf import build_prusa_native_3mf
from core.tests.test_slicer_prusa_plate import item, cube
from scripts.prusa_native_two_support_object_controls import (
    block_unpainted_with_native_volume,
)

NS = "{http://schemas.microsoft.com/3dmanufacturing/core/2015/02}"


def _parts(project):
    with zipfile.ZipFile(io.BytesIO(project)) as archive:
        return {name: archive.read(name) for name in archive.namelist()}


class PrusaNativeSupportBlockerResearchTests(unittest.TestCase):
    def test_right_only_receives_native_blocker_volume(self):
        original=build_prusa_native_3mf([
            (item(x_mm=-35),cube()),(item(x_mm=35),cube()),
        ],bed_width=250,bed_depth=210)
        before=_parts(original)
        after=_parts(block_unpainted_with_native_volume(original))
        first=SafeET.fromstring(before["3D/3dmodel.model"])
        second=SafeET.fromstring(after["3D/3dmodel.model"])
        objs_before=first.findall("./"+NS+"resources/"+NS+"object")
        objs_after=second.findall("./"+NS+"resources/"+NS+"object")
        self.assertEqual(len(objs_after),2)
        for index in (0,1):
            old=objs_before[index].find(NS+"mesh")
            new=objs_after[index].find(NS+"mesh")
            old_faces=old.find(NS+"triangles")
            new_faces=new.find(NS+"triangles")
            self.assertEqual(len(new_faces)-len(old_faces),12 if index==1 else 0)
            if index==0:
                self.assertEqual(
                    [tuple(face.attrib.items()) for face in new_faces],
                    [tuple(face.attrib.items()) for face in old_faces])
        settings=SafeET.fromstring(after["Metadata/Slic3r_PE_model.config"])
        rows=settings.findall("./object")
        self.assertEqual([len(row.findall("./volume")) for row in rows],[1,2])
        blocker=rows[1].findall("./volume")[1]
        self.assertEqual(blocker.get("firstid"),str(len(
            objs_before[1].find(NS+"mesh").find(NS+"triangles"))))
        self.assertEqual(blocker.findall("./metadata")[0].get("value"),"SupportBlocker")
        self.assertEqual(before["[Content_Types].xml"],after["[Content_Types].xml"])

    def test_single_object_cannot_be_mislabelled_as_neighbour(self):
        original=build_prusa_native_3mf(
            [(item(),cube())],bed_width=250,bed_depth=210)
        with self.assertRaisesRegex(AssertionError,"two separate objects"):
            block_unpainted_with_native_volume(original)
