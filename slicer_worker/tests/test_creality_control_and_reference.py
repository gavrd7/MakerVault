"""Pure local Creality diagnostic controls; never runs native CLI or printer."""
import io
import json
import unittest
import zipfile
from xml.etree import ElementTree as ET

from slicer_worker.creality_single_control import single_material_control
from slicer_worker.creality_reference_diagnostics import compare_projects

NS = "{http://schemas.microsoft.com/3dmanufacturing/core/2015/02}"


def fixture(*, second=True, linked=False):
    root = ET.Element(NS + "model", {"unit": "millimeter"})
    resources = ET.SubElement(root, NS + "resources")
    build = ET.SubElement(root, NS + "build")
    for idx in (1, 2) if second else (1,):
        obj = ET.SubElement(resources, NS + "object", {"id": str(idx), "type": "model"})
        if linked:
            components = ET.SubElement(obj, NS + "components")
            ET.SubElement(components, NS + "component", {"objectid": "1"})
        else:
            ET.SubElement(obj, NS + "mesh")
        ET.SubElement(build, NS + "item", {"objectid": str(idx)})
    manifest = ET.Element("config")
    for idx in (1, 2) if second else (1,):
        obj = ET.SubElement(manifest, "object", {"id": str(idx)})
        ET.SubElement(obj, "metadata", {"key": "extruder", "value": str(idx)})
        ET.SubElement(obj, "part", {"id": "1", "subtype": "normal_part"})
    plate = ET.SubElement(manifest, "plate")
    for idx in (1, 2) if second else (1,):
        row = ET.SubElement(plate, "model_instance")
        ET.SubElement(row, "metadata", {"key": "object_id", "value": str(idx)})
    assembly = ET.SubElement(manifest, "assemble")
    for idx in (1, 2) if second else (1,):
        ET.SubElement(assembly, "assemble_item", {"object_id": str(idx)})
    config = {
        "name": "project_settings",
        "filament_settings_id": ["grey", "yellow", "grey", "yellow"] if second else ["grey"],
        "filament_type": ["PLA"] * (4 if second else 1),
        "nozzle_temperature": ["210", "220", "210", "220"] if second else ["210"],
        "filament_map": ["1"] * (4 if second else 1),
        "flush_volumes_matrix": ["0"] * (16 if second else 1),
        "flush_volumes_vector": ["140"] * (8 if second else 2),
    }
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as z:
        z.writestr("3D/3dmodel.model", ET.tostring(root))
        z.writestr("Metadata/model_settings.config", ET.tostring(manifest))
        z.writestr("Metadata/project_settings.config", json.dumps(config))
        z.writestr("Metadata/creality.config", '<config/>')
        z.writestr("[Content_Types].xml", "<Types/>")
        z.writestr("_rels/.rels", "<Relationships/>")
    return buffer.getvalue()


class SingleMaterialControlTests(unittest.TestCase):
    def test_reduces_geometry_build_manifest_and_filaments(self):
        source = fixture()
        result = single_material_control(source)
        with zipfile.ZipFile(io.BytesIO(result)) as z:
            model = ET.fromstring(z.read("3D/3dmodel.model"))
            settings = ET.fromstring(z.read("Metadata/model_settings.config"))
            project = json.loads(z.read("Metadata/project_settings.config"))
        self.assertEqual(len(model.findall(".//" + NS + "resources/" + NS + "object")), 1)
        self.assertEqual(len(model.findall(".//" + NS + "build/" + NS + "item")), 1)
        self.assertEqual(len(settings.findall("object")), 1)
        self.assertEqual(len(settings.findall("./plate/model_instance")), 1)
        self.assertEqual(len(settings.findall("./assemble/assemble_item")), 1)
        self.assertEqual(project["filament_settings_id"], ["grey"])
        self.assertEqual(project["nozzle_temperature"], ["210"])
        self.assertEqual(project["flush_volumes_matrix"], ["0"])
        self.assertEqual(project["enable_prime_tower"], "0")
        # Original saved project remains unmodified.
        with zipfile.ZipFile(io.BytesIO(source)) as z:
            self.assertEqual(len(ET.fromstring(z.read("Metadata/model_settings.config")).findall("object")), 2)

    def test_rejects_incompatible_input_without_executing_engine(self):
        with self.assertRaises(ValueError):
            single_material_control(fixture(second=False))


class ReferenceComparisonTests(unittest.TestCase):
    def test_detects_relationships_and_material_shapes(self):
        candidate = fixture()
        reference = fixture(second=False, linked=True)
        report = compare_projects(candidate, reference)
        self.assertEqual(report["candidate_structure_counts"]["resource_objects"], 2)
        self.assertEqual(report["reference_structure_counts"]["resource_objects"], 1)
        self.assertEqual(report["reference_structure_counts"]["component_links"], 1)
        self.assertTrue(any(row["key"] == "filament_settings_id"
                            for row in report["different_value_shapes"]))
        self.assertNotIn("yellow", json.dumps(report))
        self.assertNotIn("grey", json.dumps(report))

    def test_rejects_duplicate_archive_entries(self):
        source = fixture()
        with zipfile.ZipFile(io.BytesIO(source)) as z:
            entries = [(name, z.read(name)) for name in z.namelist()]
        output = io.BytesIO()
        with zipfile.ZipFile(output, "w") as z:
            for name, data in entries:
                z.writestr(name, data)
            z.writestr("3D/3dmodel.model", b"<model/>")
        with self.assertRaises(ValueError):
            compare_projects(source, output.getvalue())


if __name__ == "__main__":
    unittest.main()
