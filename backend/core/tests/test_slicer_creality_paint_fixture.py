"""Synthetic Creality native painting tests never require a saved SliceJob."""
import io
import json
import zipfile
from defusedxml import ElementTree as ET

from django.test import SimpleTestCase

from core.management.commands.diagnose_creality_paint_fixture import (
    _fixture_project, _synthetic_fixture_item,
)
from core.management.commands.diagnose_creality_paint_features import (
    _cantilever_fixture_stl,
)
from core.slicer_variable_layers import orca_layer_config_ranges


class CrealitySyntheticPaintFixtureTests(SimpleTestCase):
    def setUp(self):
        self.raw = _cantilever_fixture_stl()
        self.machine = json.dumps({
            "type": "machine", "name": "Synthetic K2",
            "printable_height": "260",
            "printable_area": ["0x0", "260x0", "260x260", "0x260"],
            "single_extruder_multi_material": "1",
            "purge_in_prime_tower": "0",
        }).encode()
        self.process = json.dumps({
            "type": "process", "name": "Synthetic process",
            "enable_prime_tower": "1", "prime_tower_width": "40",
        }).encode()
        self.filaments = [
            json.dumps({
                "type": "filament", "name": name,
                "nozzle_temperature": temperature,
            }).encode()
            for name, temperature in (("Dark", "210"), ("Light", "220"))
        ]

    def test_all_synthetic_feature_projects_have_native_two_colour_facets(self):
        for feature, expected in (
                ("baseline", None),
                ("support", "paint_supports"),
                ("seam", "paint_seam"),
                ("fuzzy", "paint_fuzzy_skin"),
                ("variable", None),
                ("flushing", None)):
            with self.subTest(feature=feature):
                blob, process = _fixture_project(
                    self.raw, feature, machine=self.machine,
                    process=self.process, filaments=self.filaments,
                    width=260, depth=260)
                self.assertIsInstance(blob, bytes)
                self.assertIsInstance(process, bytes)
                with zipfile.ZipFile(io.BytesIO(blob)) as archive:
                    root = ET.fromstring(archive.read("3D/3dmodel.model"))
                    config = json.loads(archive.read("Metadata/project_settings.config"))
                    triangles = root.findall(
                        ".//{http://schemas.microsoft.com/3dmanufacturing/core/2015/02}triangle")
                    self.assertTrue(any("paint_color" in face.attrib for face in triangles))
                    if expected:
                        self.assertTrue(any(expected in face.attrib for face in triangles))
                    if feature == "variable":
                        self.assertIn("Metadata/layer_config_ranges.xml", archive.namelist())
                    if feature == "flushing":
                        self.assertEqual(float(config["flush_multiplier"]), 1.25)
                    else:
                        self.assertNotEqual(str(config.get("multicolor_method")), "1")
                    self.assertEqual(config.get("purge_in_prime_tower"), "0")

    def test_synthetic_fixture_is_disposable_and_has_valid_layer_band(self):
        obj = _synthetic_fixture_item(self.raw, "variable")
        self.assertEqual(obj["colour_paint"]["regions"][0]["slot"], 1)
        self.assertIsNotNone(orca_layer_config_ranges([(obj, self.raw)]))
        self.assertNotIn("asset_id", obj)
        self.assertNotIn("printer_id", obj)
