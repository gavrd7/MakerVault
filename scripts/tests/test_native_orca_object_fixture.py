"""Native Orca object fixture must preserve isolated settings and units."""
import io
import tempfile
import unittest
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

from scripts.build_slicer_multimodel_fixture import object_settings_fixture


class NativeObjectFixtureTests(unittest.TestCase):
    def test_each_native_setting_can_be_isolated_and_reversed(self):
        with tempfile.TemporaryDirectory() as directory:
            for setting, key, values in (
                ("wall_loops", "wall_loops", (2.0, 5.0)),
                ("sparse_infill_density", "sparse_infill_density", (0.0, 80.0)),
                ("combined", "wall_loops", (2.0, 5.0)),
            ):
                for reverse in (False, True):
                    with self.subTest(setting=setting, reverse=reverse):
                        path = Path(directory) / (setting + str(reverse) + ".3mf")
                        object_settings_fixture(path, setting=setting, reverse=reverse)
                        with zipfile.ZipFile(path) as archive:
                            config = ET.fromstring(archive.read("Metadata/model_settings.config"))
                        objects = config.findall("object")
                        self.assertEqual([row.attrib["id"] for row in objects], ["1", "2"])
                        actual = []
                        for row in objects:
                            data = {item.attrib["key"]: item.attrib["value"]
                                    for item in row.findall("metadata")}
                            if setting == "sparse_infill_density":
                                self.assertTrue(data[key].endswith("%"))
                            actual.append(float(data[key].removesuffix("%")))
                        self.assertEqual(tuple(actual), values[::-1] if reverse else values)


if __name__ == "__main__":
    unittest.main()
