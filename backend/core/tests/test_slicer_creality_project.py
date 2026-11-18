"""Creality native plate geometry candidate retains exact positions and tools."""
import io
import zipfile
from defusedxml import ElementTree as ET
from django.test import SimpleTestCase

from core.slicer_approval import fixture_stl
from core.slicer_creality_project import build_creality_positioned_plate
from core.slicer_plate_3mf import NS
from core.slicer_profiles import SlicerProfileError


class CrealityPositionedPlateTests(SimpleTestCase):
    def _objects(self):
        return [
            ({"x_mm": -18, "y_mm": 0, "rotation_deg": 0,
              "scale_percent": 100}, fixture_stl()),
            ({"x_mm": 18, "y_mm": 0, "rotation_deg": 0,
              "scale_percent": 100}, fixture_stl()),
        ]

    def test_positions_and_materials_remain_distinct(self):
        project = build_creality_positioned_plate(
            self._objects(), bed_width=260, bed_depth=260, tool_ids=[0, 1])
        with zipfile.ZipFile(io.BytesIO(project)) as zipped:
            root = ET.fromstring(zipped.read("3D/3dmodel.model"))
            settings = ET.fromstring(zipped.read("Metadata/model_settings.config"))
        ns = "{" + NS + "}"
        objects = root.findall("./" + ns + "resources/" + ns + "object")
        x_centres = []
        for obj in objects:
            xs = [float(v.attrib["x"]) for v in obj.findall(
                "./" + ns + "mesh/" + ns + "vertices/" + ns + "vertex")]
            x_centres.append((min(xs) + max(xs)) / 2)
        self.assertAlmostEqual(x_centres[0], 112, places=3)
        self.assertAlmostEqual(x_centres[1], 148, places=3)
        tools = [
            [m.attrib["value"] for m in obj.findall("metadata")
             if m.attrib.get("key") == "extruder"]
            for obj in settings.findall("object")
        ]
        self.assertEqual(tools, [["1"], ["2"]])

    def test_invalid_palette_fails_before_native_engine(self):
        with self.assertRaises(SlicerProfileError):
            build_creality_positioned_plate(
                self._objects(), bed_width=260, bed_depth=260, tool_ids=[0, 0])
