"""Bambu opt-in beta gates must fail closed before any worker/printer action."""
import os
from types import SimpleNamespace
from unittest.mock import patch, Mock
import uuid

from django.test import SimpleTestCase

from core.slicer_execution import _validate_plate_execution, SlicerExecutionError
from core.slicer_worker_client import SlicerWorkerError, run_remote_job, health


class BambuBetaExecutionGateTests(SimpleTestCase):
    def job(self, settings=None, *, plate="default", version="02.09.01.70"):
        return SimpleNamespace(
            engine="bambustudio", engine_version=version,
            plate=plate, settings={} if settings is None else settings,
            owner=None, filament_profile_id=uuid.uuid4(),
        )

    @patch("core.slicer_execution.expand_painted_settings", side_effect=lambda owner, settings: settings)
    def test_beta_off_is_rejected_even_for_simple_model(self, _expand):
        with patch.dict(os.environ, {"MAKERVAULT_SLICER_BAMBU_BETA_ENABLED": "0"}):
            with self.assertRaisesRegex(SlicerExecutionError, "not enabled"):
                _validate_plate_execution(self.job())

    @patch("core.slicer_execution.expand_painted_settings", side_effect=lambda owner, settings: settings)
    def test_only_single_material_unmodified_stl_admitted(self, _expand):
        base = {"instance_id":"one", "asset_id":str(uuid.uuid4()),
                "x_mm":0,"y_mm":0,"rotation_deg":0,"z_mm":0,
                "rotation_xyz_deg":[0,0],"scale_percent":100,
                "scale_xyz_percent":[100,100,100]}
        with patch.dict(os.environ, {"MAKERVAULT_SLICER_BAMBU_BETA_ENABLED": "1"}):
            self.assertTrue(_validate_plate_execution(self.job()))
            self.assertTrue(_validate_plate_execution(
                self.job({"plate_objects":[base]})))
            with self.assertRaisesRegex(SlicerExecutionError, "unmodified STL"):
                _validate_plate_execution(self.job({"plate_objects":[base,base]}))
            with self.assertRaisesRegex(SlicerExecutionError, "single-material"):
                _validate_plate_execution(self.job({"multi_material_test":True}))
            with self.assertRaisesRegex(SlicerExecutionError, "native preset default"):
                _validate_plate_execution(self.job(plate="textured"))
            with self.assertRaisesRegex(SlicerExecutionError, "not enabled"):
                _validate_plate_execution(self.job(version="02.10.00.00"))
            painted={**base,"colour_paint":{"regions":[{"kind":"test"}]}}
            with self.assertRaisesRegex(SlicerExecutionError, "painting"):
                _validate_plate_execution(self.job({"plate_objects":[painted]}))
            bad={**base,"filament_profile_id":str(uuid.uuid4())}
            with self.assertRaisesRegex(SlicerExecutionError, "single filament"):
                _validate_plate_execution(self.job({"plate_objects":[bad]}))

    def test_bambu_health_is_hidden_without_both_app_and_worker_betagate(self):
        import json
        data={"ready":True,"engine":"bambustudio","version":"02.09.01.70",
              "binary_sha256":"a"*64,
              "engines":{"bambustudio":{
                  "version":"02.09.01.70","binary_sha256":"a"*64,"ready":True}}}
        response=Mock(status_code=200, content=json.dumps(data).encode())
        response.json.return_value=data
        session=Mock()
        session.get.return_value=response
        with patch("core.slicer_worker_client.worker_settings",
                   return_value=("http://slicer-worker:8088", "x"*40)),\
             patch("core.slicer_worker_client._session", return_value=session):
            with patch.dict(os.environ, {"MAKERVAULT_SLICER_BAMBU_BETA_ENABLED":"0"}):
                self.assertNotIn("bambustudio", health()["engines"])
            with patch.dict(os.environ, {"MAKERVAULT_SLICER_BAMBU_BETA_ENABLED":"1"}):
                self.assertEqual(health()["engines"]["bambustudio"]["version"],"02.09.01.70")

    def test_bambu_send_refused_before_network_with_beta_off_or_wrong_version(self):
        data=(b"dummy",)*4
        with patch.dict(os.environ, {"MAKERVAULT_SLICER_BAMBU_BETA_ENABLED":"0"}):
            with self.assertRaisesRegex(SlicerWorkerError, "Unsupported"):
                run_remote_job(uuid.uuid4(),"bambustudio","02.09.01.70",*data)
        with patch.dict(os.environ, {"MAKERVAULT_SLICER_BAMBU_BETA_ENABLED":"1"}):
            with self.assertRaisesRegex(SlicerWorkerError, "Unsupported"):
                run_remote_job(uuid.uuid4(),"bambustudio","02.10.00.00",*data)
