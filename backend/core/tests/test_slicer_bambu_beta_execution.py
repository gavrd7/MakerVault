"""Bambu Studio follows the same authenticated worker and plate handling as Orca."""
from types import SimpleNamespace
from unittest.mock import Mock, patch
import uuid

from django.test import SimpleTestCase

from core.slicer_execution import _validate_plate_execution, SlicerExecutionError
from core.slicer_worker_client import SlicerWorkerError, run_remote_job, health


class BambuEngineExecutionTests(SimpleTestCase):
    def job(self, settings=None, *, plate="default", version="02.09.01.70"):
        return SimpleNamespace(
            engine="bambustudio", engine_version=version,
            plate=plate, settings={} if settings is None else settings,
            owner=None, filament_profile_id=uuid.uuid4(),
            printer_profile=SimpleNamespace(),
        )

    @patch("core.slicer_execution.expand_painted_settings",
           side_effect=lambda owner, settings: settings)
    @patch("core.slicer_execution.trusted_plate_dimensions", return_value=(256, 256))
    @patch("core.slicer_execution.single_material_slice_assignment")
    def test_standard_plate_admission_without_opt_in_switch(self, _assign, _dims, _expand):
        base = {"instance_id": "one", "asset_id": str(uuid.uuid4()),
                "x_mm": 0, "y_mm": 0, "rotation_deg": 0, "z_mm": 0,
                "rotation_xyz_deg": [0, 0], "scale_percent": 100,
                "scale_xyz_percent": [100, 100, 100]}
        self.assertTrue(_validate_plate_execution(self.job()))
        self.assertTrue(_validate_plate_execution(
            self.job({"plate_objects": [base]})))
        # A transformed model and multi-model plate now follow normal
        # MakerVault 3MF geometry validation; no single-STL Beta limit.
        transformed = {**base, "instance_id": "two", "x_mm": 15}
        self.assertTrue(_validate_plate_execution(
            self.job({"plate_objects": [transformed]})))
        self.assertTrue(_validate_plate_execution(
            self.job({"plate_objects": [base, transformed]})))
        with self.assertRaisesRegex(SlicerExecutionError, "native multi-filament"):
            _validate_plate_execution(self.job({
                "multi_material_test": True,
                "plate_objects": [base, transformed],
            }))
        painted = {**base, "colour_paint": {"regions": [{"kind": "test"}]}}
        with self.assertRaisesRegex(SlicerExecutionError, "object-specific"):
            _validate_plate_execution(self.job({"plate_objects": [painted]}))

    def test_bambu_installed_health_visible_without_beta_setting(self):
        import json
        data = {
            "ready": True, "engine": "bambustudio", "version": "02.09.01.70",
            "binary_sha256": "a" * 64,
            "engines": {
                "bambustudio": {
                    "version": "02.09.01.70",
                    "binary_sha256": "a" * 64,
                    "ready": True,
                }
            }
        }
        response = Mock(status_code=200, content=json.dumps(data).encode())
        response.json.return_value = data
        session = Mock()
        session.get.return_value = response
        with patch("core.slicer_worker_client.worker_settings",
                   return_value=("http://slicer-worker:8088", "x" * 40)), \
             patch("core.slicer_worker_client._session", return_value=session):
            self.assertEqual(
                health()["engines"]["bambustudio"]["version"], "02.09.01.70")

    def test_unreviewed_version_rejected_before_worker_network(self):
        with self.assertRaisesRegex(SlicerWorkerError, "Unsupported"):
            run_remote_job(uuid.uuid4(), "bambustudio", "02.10.00.00",
                           b"model", b"printer", b"filament", b"process")
