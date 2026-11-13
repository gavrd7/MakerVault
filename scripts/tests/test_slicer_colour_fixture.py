import json
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase

from scripts.build_slicer_colour_fixture import generate


class NativeK2ColourFixtureTests(TestCase):
    def test_two_colour_variants_preserve_native_material_properties(self):
        with TemporaryDirectory() as tmp:
            source = Path(tmp) / "filament.json"
            original = {
                "name": "Generic PLA @K2-all",
                "filament_diameter": ["1.75"],
                "filament_type": ["PLA"],
                "default_filament_colour": ["#0000FF"],
                "filament_max_volumetric_speed": ["20"],
            }
            source.write_text(json.dumps(original))
            black = generate(source, Path(tmp) / "black.json", "#000000")
            white = generate(source, Path(tmp) / "white.json", "#ffffff")
            first = json.loads(black.read_bytes())
            second = json.loads(white.read_bytes())
            self.assertEqual(first["default_filament_colour"], ["#000000"])
            self.assertEqual(second["default_filament_colour"], ["#FFFFFF"])
            self.assertEqual(first["filament_max_volumetric_speed"],
                             second["filament_max_volumetric_speed"])
            self.assertEqual(json.loads(source.read_bytes()), original)
            with self.assertRaisesRegex(ValueError, "overwrite"):
                generate(source, black, "#FFFFFF")

    def test_colour_fixture_rejects_invalid_rgb(self):
        with TemporaryDirectory() as tmp:
            source = Path(tmp) / "filament.json"
            source.write_text('{"filament_diameter":["1.75"]}')
            with self.assertRaises(ValueError):
                generate(source, Path(tmp) / "invalid.json", "black")
