import io
import zipfile
import unittest
from xml.etree import ElementTree as ET

from slicer_worker.three_mf_validation import validate_worker_3mf, CORE_NS
from slicer_worker.runner import WorkerError


def compact_fixture(count=20, *, transform=None):
    q = "{" + CORE_NS + "}"
    root = ET.Element(q + "model", {
        "unit": "millimeter", "{http://www.w3.org/XML/1998/namespace}lang": "en-US"
    })
    resources = ET.SubElement(root, q+"resources")
    source = ET.SubElement(resources, q+"object", {"id":"1", "type":"model"})
    mesh = ET.SubElement(source, q+"mesh")
    vertices = ET.SubElement(mesh, q+"vertices")
    for x,y,z in ((0,0,0),(1,0,0),(0,1,0)):
        ET.SubElement(vertices, q+"vertex", {"x":str(x),"y":str(y),"z":str(z)})
    triangles = ET.SubElement(mesh, q+"triangles")
    ET.SubElement(triangles,q+"triangle",{"v1":"0","v2":"1","v3":"2"})
    group = ET.SubElement(resources,q+"object",{"id":"2","type":"model"})
    components = ET.SubElement(group,q+"components")
    for i in range(count):
        ET.SubElement(components,q+"component",{
            "objectid":"1",
            "transform": transform or "1 0 0 0 1 0 0 0 1 %d 0 0" % (i*2),
        })
    build = ET.SubElement(root,q+"build")
    ET.SubElement(build,q+"item",{"objectid":"2", "transform":"1 0 0 0 1 0 0 0 1 0 0 0"})
    file = io.BytesIO()
    with zipfile.ZipFile(file, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("3D/3dmodel.model",ET.tostring(root,encoding="utf-8"))
        archive.writestr("[Content_Types].xml",b"<Types/>")
        archive.writestr("_rels/.rels",b"<Relationships/>")
    return file.getvalue()


class CompactInstanceValidationTests(unittest.TestCase):
    def test_explicit_orca_compact_contract_accepts_twenty_instances(self):
        self.assertTrue(validate_worker_3mf(
            compact_fixture(),allow_compact_instances=True))

    def test_existing_3mf_contract_rejects_components(self):
        with self.assertRaises(WorkerError):
            validate_worker_3mf(compact_fixture())

    def test_multimaterial_contract_rejects_components(self):
        with self.assertRaises(WorkerError):
            validate_worker_3mf(compact_fixture(),
                allow_compact_instances=True,native_tool_count=2)

    def test_rejects_component_outside_safe_geometry(self):
        with self.assertRaises(WorkerError):
            validate_worker_3mf(compact_fixture(
                transform="1 0 0 0 1 0 0 0 1 0 0 -10"),allow_compact_instances=True)

    def test_rejects_collapsed_instance(self):
        with self.assertRaises(WorkerError):
            validate_worker_3mf(compact_fixture(
                transform="0 0 0 0 1 0 0 0 1 0 0 0"),allow_compact_instances=True)
