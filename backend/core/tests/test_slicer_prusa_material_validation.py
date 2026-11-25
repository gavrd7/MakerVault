"""Native material research contract must remain separate from live worker."""
import io
import zipfile
from unittest import TestCase
from xml.etree import ElementTree as ET

from core.slicer_prusa_colour_project import build_prusa_colour_candidate
from core.slicer_prusa_material_project import add_prusa_native_model_tools
from core.slicer_prusa_3mf import build_prusa_native_3mf
from core.tests.test_slicer_prusa_machine_topology import ini
from core.tests.test_slicer_prusa_plate import item, cube
from scripts.prusa_generate_mmu_paint import fixture
from slicer_worker.prusa_material_validation import validate_prusa_material_candidate
from slicer_worker.prusa_3mf_validation import validate_prusa_native_3mf
from slicer_worker.runner import WorkerError


def mutate(project, part, edit):
    dst=io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(project)) as src, zipfile.ZipFile(
            dst,"w",compression=zipfile.ZIP_DEFLATED) as out:
        for name in src.namelist():
            content=src.read(name)
            if name==part:
                root=ET.fromstring(content)
                edit(root)
                content=ET.tostring(root)
            out.writestr(name,content)
    return dst.getvalue()


class PrusaResearchMaterialValidationTests(TestCase):
    def models(self):
        rows=[(item(x_mm=-35),cube()),(item(x_mm=35),cube())]
        base=build_prusa_native_3mf(rows,bed_width=250,bed_depth=210)
        return add_prusa_native_model_tools(base,ini("0.4,0.4","1"),[1,2])["project"]

    def painted(self):
        raw,_painted,_tags,paint=fixture(include_paint=True)
        row={**item(),"colour_paint":paint}
        return build_prusa_colour_candidate(
            row,raw,printer_ini=ini("0.4,0.4,0.4,0.4,0.4","1"),
            colour_tool_indices={1:1},bed_width=250,bed_depth=210)

    def test_models_have_strict_tool_assignments(self):
        project=self.models()
        self.assertEqual(validate_prusa_material_candidate(project,printer_ini=ini("0.4,0.4","1"),tools=[1,2])["tools"],(1,2))
        for expected in ([2,1],[1,3],[1,1],[],[1,True]):
            with self.subTest(expected=expected),self.assertRaises(WorkerError):
                validate_prusa_material_candidate(project,tools=expected)
        with self.assertRaises(WorkerError):
            validate_prusa_native_3mf(project)

    def test_painted_candidate_has_qualified_state_and_is_not_live_worker_accepted(self):
        project=self.painted()
        receipt=validate_prusa_material_candidate(project,printer_ini=ini("0.4,0.4,0.4,0.4,0.4","1"),colour=True)
        self.assertGreater(receipt["colour_facets"],0)
        with self.assertRaises(WorkerError):
            validate_prusa_native_3mf(project)

    def test_wrong_native_topology_is_rejected(self):
        project=self.models()
        for machine in (ini("0.4"), ini("0.4,0.4","0",binary_gcode="1")):
            with self.subTest(machine=machine),self.assertRaises(WorkerError):
                validate_prusa_material_candidate(project,printer_ini=machine,tools=[1,2])
        colour=self.painted()
        with self.assertRaises(WorkerError):
            validate_prusa_material_candidate(
                colour,printer_ini=ini("0.4,0.4","0"),colour=True)

    def test_tampered_native_material_annotations_fail(self):
        project=self.models()
        def inject(root):
            ET.SubElement(root.find("./object"),"metadata",
                          {"type":"object","key":"post_process","value":"bad"})
        bad=mutate(project,"Metadata/Slic3r_PE_model.config",inject)
        with self.assertRaises(WorkerError):
            validate_prusa_material_candidate(bad,printer_ini=ini("0.4,0.4","1"),tools=[1,2])
        colour=self.painted()
        ns="{http://schemas.microsoft.com/3dmanufacturing/core/2015/02}"
        mmu="{http://schemas.slic3r.org/3mf/2017/06}mmu_segmentation"
        def corrupt(root):
            face=next(n for n in root.findall(
                "./"+ns+"resources/"+ns+"object/"+ns+"mesh/"+ns+"triangles/"+ns+"triangle")
                if mmu in n.attrib)
            face.set(mmu,"FFFF")
        with self.assertRaises(WorkerError):
            validate_prusa_material_candidate(
                mutate(colour,"3D/3dmodel.model",corrupt),
                printer_ini=ini("0.4,0.4,0.4,0.4,0.4","1"),colour=True)
        with self.assertRaises(WorkerError):
            validate_prusa_material_candidate(colour,printer_ini=ini("0.4,0.4","1"),tools=[1,2])
