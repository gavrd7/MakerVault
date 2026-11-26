"""Regression coverage for cross-engine CPU preparation and isolation."""
import os
from unittest.mock import patch

from django.test import SimpleTestCase

from core.slicer_approval import fixture_stl
from core.slicer_parallel_geometry import (
    _local_parallel_slots, prepared_mesh_batches,
)
from core.slicer_plate_3mf import NS


class ParallelGeometryExecutionTests(SimpleTestCase):
    def test_child_imports_core_package_without_parent_pythonpath(self):
        # Historical fixture scripts inserted backend/ into sys.path only.
        # An exec-based child must not assume the caller exported PYTHONPATH.
        source = fixture_stl()
        entries = [(1, source, {"colour_tool_indices": {1: 0}}),
                   (2, source, {"colour_tool_indices": {1: 0}})]
        with patch("core.slicer_parallel_geometry.preparation_worker_count", return_value=2), \
                patch("core.slicer_parallel_geometry._MIN_PARALLEL_INPUT_BYTES", 0), \
                patch.dict(os.environ, {"PYTHONPATH": ""}):
            with prepared_mesh_batches(
                    entries, estimated_bytes_per_worker=4 * 1024**2) as results:
                rendered = list(results)
        self.assertEqual(len(rendered), 2)
        self.assertEqual([entry[0] for entry in rendered], [1, 2])
        self.assertTrue(all(b"<" in result for _, _, result in rendered))
        self.assertTrue(all(NS.encode() in result for _, _, result in rendered))

    def test_single_core_never_starts_subprocess(self):
        raw = fixture_stl()
        with patch("core.slicer_parallel_geometry.preparation_worker_count", return_value=1), \
                patch("core.slicer_parallel_geometry.subprocess.Popen") as popen:
            with prepared_mesh_batches(
                    [(1, raw), (2, raw)],
                    estimated_bytes_per_worker=4 * 1024**2) as results:
                self.assertEqual([result for _, _, result in results], [None, None])
        popen.assert_not_called()

    def test_small_models_stay_serial_even_on_many_core_hosts(self):
        raw = fixture_stl()
        with patch("core.slicer_parallel_geometry.preparation_worker_count", return_value=16), \
                patch("core.slicer_parallel_geometry.subprocess.Popen") as popen:
            with prepared_mesh_batches(
                    [(1, raw), (2, raw)],
                    estimated_bytes_per_worker=4 * 1024**2) as results:
                self.assertEqual([result for _, _, result in results], [None, None])
        popen.assert_not_called()

    def test_local_slot_context_never_swallows_caller_error(self):
        with self.assertRaisesRegex(OSError, "work error"):
            with _local_parallel_slots(2):
                raise OSError("work error")
