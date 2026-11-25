"""Prusa research tool mapping strictly preserves immutable model geometry."""
import io
import zipfile
from unittest import TestCase
from defusedxml import ElementTree as SafeET

from core.slicer_prusa_material_project import add_prusa_native_model_tools
from core.slicer_prusa_3mf import build_prusa_native_3mf
from core.tests.test_slicer_prusa_machine_topology import ini
from core.tests.test_slicer_prusa_plate import item, cube
from core.slicer_profiles import SlicerProfileError


class PrusaMaterialProjectTests(TestCase):
    def source(self):
        return build_prusa_native_3mf([
            (item(x_mm=-35),cube()),(item(x_mm=35),cube()),
        ],bed_width=250,bed_depth=210)

    def test_mmu_and_xl_get_native_one_based_tool_assignment(self):
        base=self.source()
        for changer in ("0","1"):
            with self.subTest(changer=changer):
                result=add_prusa_native_model_tools(
                    base,ini("0.4,0.4",changer),[1,2])
                self.assertEqual(result["topology"]["physical_nozzle_count"],
                                 1 if changer=="1" else 2)
                with zipfile.ZipFile(io.BytesIO(base)) as source:
                    with zipfile.ZipFile(io.BytesIO(result["project"])) as dest:
                        self.assertEqual(source.namelist(),dest.namelist())
                        for name in source.namelist():
                            if name!="Metadata/Slic3r_PE_model.config":
                                self.assertEqual(source.read(name),dest.read(name))
                        config=SafeET.fromstring(dest.read(
                            "Metadata/Slic3r_PE_model.config"))
                self.assertEqual([obj.find("./metadata[@key='extruder']").get("value")
                                  for obj in config],["1","2"])

    def test_unsafe_tool_vectors_refused(self):
        for tools in ([1,1],[0,2],[1,3],[True,2],[1],[]):
            with self.subTest(tools=tools),self.assertRaises(SlicerProfileError):
                add_prusa_native_model_tools(
                    self.source(),ini("0.4,0.4","1"),tools)

    def test_rewriting_already_assigned_project_fails(self):
        source=self.source()
        compiled=add_prusa_native_model_tools(
            source,ini("0.4,0.4","1"),[1,2])["project"]
        with self.assertRaises(SlicerProfileError):
            add_prusa_native_model_tools(
                compiled,ini("0.4,0.4","1"),[2,1])
