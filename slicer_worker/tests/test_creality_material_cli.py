"""Tests for Creality Print's official 1-based multi-STL material CLI contract."""
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase

from slicer_worker.creality_material_cli import (
    CrealityMaterialRouteError, native_stl_material_arguments,
)


class CrealityMaterialCliTests(TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.models = [root / "a.stl", root / "b.stl"]
        self.filaments = [root / "pla.json", root / "petg.json"]
        for p in self.models + self.filaments:
            p.write_bytes(b"fixture")

    def test_two_models_map_to_distinct_logical_tools(self):
        args = native_stl_material_arguments(self.models, self.filaments, [2, 1])
        self.assertEqual(args[:4], [
            "--load-filaments", ";".join(map(str, self.filaments)),
            "--load-filament-ids", "2,1",
        ])
        self.assertEqual(args[4:], list(map(str, self.models)))

    def test_physical_slot_labels_are_not_accepted_as_tool_ids(self):
        for slots in ([0, 1], [1, 3], ["1", "2"], [True, 2], [1, 1]):
            with self.subTest(slots=slots):
                with self.assertRaises(CrealityMaterialRouteError):
                    native_stl_material_arguments(self.models, self.filaments, slots)

    def test_no_3mf_with_stl_specific_ids(self):
        self.models[0].rename(self.models[0].with_suffix(".3mf"))
        with self.assertRaises(CrealityMaterialRouteError):
            native_stl_material_arguments(
                [self.models[0].with_suffix(".3mf"), self.models[1]],
                self.filaments, [1, 2])

    def test_missing_file_rejected(self):
        self.models[0].unlink()
        with self.assertRaises(CrealityMaterialRouteError):
            native_stl_material_arguments(self.models, self.filaments, [1, 2])
