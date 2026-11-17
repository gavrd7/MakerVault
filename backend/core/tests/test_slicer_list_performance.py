"""Regression checks for bounded owner-scoped slicer list optimisations."""
import uuid
from types import SimpleNamespace
from unittest.mock import patch

from django.test import SimpleTestCase

from core.slicer_api import _job_source_ids, _native_parent_ids


class SlicerListPerformanceTests(SimpleTestCase):
    def test_saved_plate_source_ids_include_every_model(self):
        primary, extra, other = (uuid.uuid4() for _ in range(3))
        job = SimpleNamespace(
            input_asset_id=primary,
            settings={"plate_objects": [{"asset_id": str(extra)}],
                      "plates": [{"objects": [{"asset_id": str(other)}]}]},
        )
        self.assertEqual(_job_source_ids(job),
                         {str(primary), str(extra), str(other)})

    def test_cached_native_dependency_ids_do_not_reopen_files(self):
        parent = uuid.uuid4()
        row = SimpleNamespace(
            pk=parent, owner_id=uuid.uuid4(), engine="orcaslicer",
            engine_version="2.5.0", kind="process", name="Parent",
            source_scope="official", content_sha256="a" * 64,
            file_asset_id=uuid.uuid4(),
        )
        with patch("core.slicer_api.cache.get", return_value=[str(parent)]) as get_cached, \
             patch("core.slicer_api.cache.set") as set_cached:
            self.assertEqual(_native_parent_ids([row]), {parent})
            get_cached.assert_called_once()
            set_cached.assert_not_called()
