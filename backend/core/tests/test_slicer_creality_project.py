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

    def test_creality_self_contained_project_embeds_profiles_and_bounded_tower(self):
        import json
        from core.slicer_creality_project import build_creality_project_candidate
        plate = build_creality_positioned_plate(
            self._objects(), bed_width=260, bed_depth=260, tool_ids=[0, 1])
        printer = json.dumps({
            "type": "machine", "name": "Creality K2 0.4 nozzle",
            "printable_height": "260",
            "printable_area": ["0x0", "260x0", "260x260", "0x260"],
        }).encode()
        process = json.dumps({
            "type": "process", "name": "0.20mm Standard",
            "enable_prime_tower": "1", "prime_tower_width": "40",
            "layer_height": "0.2",
        }).encode()
        filament = lambda name, temp: json.dumps({
            "type": "filament", "name": name,
            "filament_type": "PLA", "nozzle_temperature": str(temp),
        }).encode()
        result = build_creality_project_candidate(
            plate, printer=printer, process=process,
            filaments=[filament("grey", 210), filament("yellow", 220)],
            bed_width=260, bed_depth=260)
        with zipfile.ZipFile(io.BytesIO(result)) as package:
            self.assertEqual(len(package.namelist()), 6)
            self.assertIn("Metadata/creality.config", package.namelist())
            project = json.loads(package.read("Metadata/project_settings.config"))
            model_root = ET.fromstring(package.read("3D/3dmodel.model"))
            app = [n.text for n in model_root if n.tag.endswith("metadata")
                   and n.attrib.get("name") == "Application"]
            self.assertEqual(app, ["Creality_Print V7.3.1"])
        self.assertEqual(project["filament_settings_id"], ["grey", "yellow"])
        self.assertEqual(project["nozzle_temperature"], ["210", "220"])
        self.assertEqual(project["from"], "project")
        self.assertEqual(project["name"], "project_settings")
        self.assertEqual(len(project["wipe_tower_x"]), 1)
        self.assertLess(float(project["wipe_tower_x"][0]), 260)
        self.assertLess(float(project["wipe_tower_y"][0]), 260)

    def test_filament_option_merge_flattens_native_singleton_vectors(self):
        import json
        from core.slicer_creality_project import build_creality_project_candidate
        plate = build_creality_positioned_plate(
            self._objects(), bed_width=260, bed_depth=260, tool_ids=[0, 1])
        printer = json.dumps({
            "type": "machine", "name": "Creality K2",
            "nozzle_diameter": ["0.4"],
        }).encode()
        process = json.dumps({
            "type": "process", "name": "0.20mm",
            "enable_prime_tower": "0",
        }).encode()
        filament = lambda name, temp: json.dumps({
            "type": "filament", "name": name,
            "filament_type": ["PLA"], "filament_diameter": ["1.75"],
            "nozzle_temperature": [str(temp)],
            "fan_cooling_layer_time": ["12"],
            "filament_minimal_purge_on_wipe_tower": ["15"],
            "filament_shrinkage_compensation_z": ["100%"],
        }).encode()
        result = build_creality_project_candidate(
            plate, printer=printer, process=process,
            filaments=[filament("grey", 210), filament("yellow", 220)])
        with zipfile.ZipFile(io.BytesIO(result)) as package:
            config = json.loads(package.read("Metadata/project_settings.config"))
        self.assertEqual(config["nozzle_temperature"], ["210", "220"])
        self.assertEqual(config["filament_diameter"], ["1.75", "1.75"])
        self.assertEqual(config["fan_cooling_layer_time"], ["12", "12"])
        self.assertEqual(config["filament_minimal_purge_on_wipe_tower"], ["15", "15"])
        self.assertEqual(config["filament_shrinkage_compensation_z"], ["100%", "100%"])
        self.assertEqual(config["nozzle_diameter"], ["0.4"])
        self.assertEqual(config["filament_map"], ["1", "1"])

    def test_invalid_palette_fails_before_native_engine(self):
        with self.assertRaises(SlicerProfileError):
            build_creality_positioned_plate(
                self._objects(), bed_width=260, bed_depth=260, tool_ids=[0, 0])
