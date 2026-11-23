"""Ensure only explicitly requested, safe nested modifier fixture 3MFs pass."""
import io
import unittest
import zipfile
from xml.etree import ElementTree as ET

from slicer_worker.runner import WorkerError
from slicer_worker.three_mf_validation import validate_worker_3mf


NS = "http://schemas.microsoft.com/3dmanufacturing/core/2015/02"
I3 = "1 0 0 0 1 0 0 0 1 0 0 0"
I4 = "1 0 0 0 0 1 0 0 0 0 1 0 0 0 0 1"


def fixture(*, malicious=False, printable_modifier=False):
    core = "{" + NS + "}"
    root = ET.Element(core + "model", {"unit": "millimeter"})
    resources = ET.SubElement(root, core + "resources")
    parent = ET.SubElement(resources, core + "object", {"id": "1", "type": "model"})
    components = ET.SubElement(parent, core + "components")
    for identifier in (2, 3):
        ET.SubElement(components, core + "component", {
            "objectid": str(identifier), "transform": I3,
        })
        obj = ET.SubElement(resources, core + "object", {
            "id": str(identifier), "type": "model",
        })
        mesh = ET.SubElement(obj, core + "mesh")
        vertices = ET.SubElement(mesh, core + "vertices")
        for x, y, z in ((0, 0, 0), (10, 0, 0), (0, 10, 0), (0, 0, 10)):
            ET.SubElement(vertices, core + "vertex", {
                "x": str(x), "y": str(y), "z": str(z),
            })
        triangles = ET.SubElement(mesh, core + "triangles")
        for a, b, c in ((0, 1, 2), (0, 3, 1), (0, 2, 3), (1, 3, 2)):
            ET.SubElement(triangles, core + "triangle", {
                "v1": str(a), "v2": str(b), "v3": str(c),
            })
    build = ET.SubElement(root, core + "build")
    ET.SubElement(build, core + "item", {"objectid": "1", "transform": I3})
    config = ET.Element("config")
    setting = ET.SubElement(config, "object", {"id": "1"})
    for identifier, subtype in ((2, "normal_part"), (3, "normal_part" if printable_modifier else "modifier_part")):
        part = ET.SubElement(setting, "part", {
            "id": str(identifier), "subtype": subtype,
        })
        ET.SubElement(part, "metadata", {"key": "name", "value": "Fixture"})
        ET.SubElement(part, "metadata", {"key": "matrix", "value": I4})
        if identifier == 3:
            ET.SubElement(part, "metadata", {
                "key": "before_layer_gcode" if malicious else "sparse_infill_density",
                "value": "G28" if malicious else "50%",
            })
    plate = ET.SubElement(config, "plate")
    ET.SubElement(plate, "metadata", {"key": "plater_id", "value": "1"})
    instance = ET.SubElement(plate, "model_instance")
    for k, v in (("object_id", "1"), ("instance_id", "0"), ("identify_id", "1")):
        ET.SubElement(instance, "metadata", {"key": k, "value": v})
    payload = {
        "3D/3dmodel.model": ET.tostring(root),
        "Metadata/model_settings.config": ET.tostring(config),
        "_rels/.rels": b"<Relationships/>",
        "[Content_Types].xml": b"<Types/>",
    }
    with io.BytesIO() as raw:
        with zipfile.ZipFile(raw, "w", compression=zipfile.ZIP_DEFLATED) as out:
            for name, data in payload.items():
                out.writestr(name, data)
        return raw.getvalue()


class NativeModifierFixtureValidationTests(unittest.TestCase):
    def test_nested_modifiers_denied_by_default_and_explicitly_admitted(self):
        data = fixture()
        with self.assertRaises(WorkerError):
            validate_worker_3mf(data)
        self.assertTrue(validate_worker_3mf(
            data, allow_native_modifier_fixture=True))

    def test_modifier_cannot_be_printable_or_inject_scripts(self):
        for data in (fixture(printable_modifier=True), fixture(malicious=True)):
            with self.subTest(data=data[:20]), self.assertRaises(WorkerError):
                validate_worker_3mf(data, allow_native_modifier_fixture=True)

    def test_modifier_flag_cannot_combine_with_material_palette(self):
        with self.assertRaises(WorkerError):
            validate_worker_3mf(fixture(), allow_native_modifier_fixture=True,
                                native_tool_count=2)


if __name__ == "__main__":
    unittest.main()
