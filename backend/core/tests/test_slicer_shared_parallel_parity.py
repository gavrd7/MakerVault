"""The common performance scheduler must not change engine-native geometry.

These cover the existing Creality/Prusa STL route and Orca/Bambu 3MF
building route, with subprocesses forced on small deterministic fixtures.
"""
import io
import zipfile
from unittest.mock import patch

from django.test import SimpleTestCase

from core.slicer_approval import fixture_stl
from core.slicer_creality_plate import build_creality_single_filament_plate
from core.slicer_prusa_plate import build_prusa_placed_stl
from core.slicer_plate_3mf import build_plate_3mf


def _item(x):
    return {"x_mm": x, "y_mm": 0, "z_mm": 0,
            "rotation_deg": 0, "rotation_xyz_deg": [0, 0],
            "scale_percent": 100, "scale_xyz_percent": [100, 100, 100]}


class SharedAdaptiveParityTests(SimpleTestCase):
    def _sequential_and_parallel(self, builder, *args, **kwargs):
        with patch("core.slicer_parallel_geometry.preparation_worker_count", return_value=1):
            sequential = builder(*args, **kwargs)
        with patch("core.slicer_parallel_geometry.preparation_worker_count", return_value=2), \
                patch("core.slicer_parallel_geometry._MIN_PARALLEL_INPUT_BYTES", 0):
            parallel = builder(*args, **kwargs)
        return sequential, parallel

    def test_prusa_placed_stl_matches_parallel_byte_for_byte(self):
        raw = fixture_stl()
        rows = [(_item(-35), raw), (_item(35), raw.replace(b"10", b"12"))]
        a, b = self._sequential_and_parallel(
            build_prusa_placed_stl, rows, bed_width=220, bed_depth=220)
        self.assertEqual(a, b)

    def test_creality_placed_stl_matches_parallel_byte_for_byte(self):
        raw = fixture_stl()
        rows = [(_item(-35), raw), (_item(35), raw.replace(b"10", b"12"))]
        a, b = self._sequential_and_parallel(
            build_creality_single_filament_plate, rows, bed_width=220, bed_depth=220)
        self.assertEqual(a, b)

    def test_common_3mf_output_matches_parallel(self):
        raw = fixture_stl()
        rows = [(_item(-35), raw), (_item(35), raw.replace(b"10", b"12"))]
        a, b = self._sequential_and_parallel(
            build_plate_3mf, rows, bed_width=220, bed_depth=220)
        with zipfile.ZipFile(io.BytesIO(a)) as first, zipfile.ZipFile(io.BytesIO(b)) as second:
            self.assertEqual(set(first.namelist()), set(second.namelist()))
            for name in first.namelist():
                self.assertEqual(first.read(name), second.read(name), name)

    def test_native_tool_assignments_survive_parallel_transport(self):
        raw = fixture_stl()
        rows = [(_item(-35), raw), (_item(35), raw)]
        a, b = self._sequential_and_parallel(
            build_plate_3mf, rows, bed_width=220, bed_depth=220,
            native_tool_indices=[0, 1],
            native_colour_tools=[{0: 0}, {0: 1}])
        with zipfile.ZipFile(io.BytesIO(a)) as first, zipfile.ZipFile(io.BytesIO(b)) as second:
            self.assertEqual(first.read("3D/3dmodel.model"),
                             second.read("3D/3dmodel.model"))
            self.assertEqual(first.read("Metadata/model_settings.config"),
                             second.read("Metadata/model_settings.config"))
