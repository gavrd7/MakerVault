"""No Bambu Beta G-code can enter any printer upload or print path."""
from types import SimpleNamespace
from unittest.mock import patch
import uuid
from django.test import SimpleTestCase
from core.printer_gcode_submission import submit, GcodeSubmissionError


class BambuBetaPrintRefusalTests(SimpleTestCase):
    @patch("core.printer_gcode_submission.FileAsset.objects.filter")
    def test_offline_beta_rejected_before_any_transfer_for_upload_or_print(self, find_asset):
        user=SimpleNamespace(pk=uuid.uuid4())
        asset=SimpleNamespace(
            pk=uuid.uuid4(), metadata={
                "extension":".gcode", "generated_by":"makervault-slicer",
                "engine":"bambustudio", "bambu_beta":True,
                "printer_submission_verified":False,
            },
        )
        find_asset.return_value.first.return_value=asset
        connection=SimpleNamespace()
        for action in ("upload","print"):
            with self.subTest(action=action):
                payload={"confirmed":True,"source":"makervault","action":action,
                         "request_id":str(uuid.uuid4()),"file_asset_id":str(asset.pk)}
                with self.assertRaisesRegex(GcodeSubmissionError, "not approved"):
                    submit(connection,user,payload)

    @patch("core.printer_gcode_submission.FileAsset.objects.filter")
    def test_renamed_or_saved_beta_still_refused_by_generated_engine_provenance(self, find_asset):
        user=SimpleNamespace(pk=uuid.uuid4())
        asset=SimpleNamespace(pk=uuid.uuid4(),metadata={
            "extension":".gcode", "engine":"bambustudio",
            "generated_by":"makervault-slicer",
        })
        find_asset.return_value.first.return_value=asset
        payload={"confirmed":True,"source":"makervault","action":"print",
                 "request_id":str(uuid.uuid4()),"file_asset_id":str(asset.pk)}
        with self.assertRaisesRegex(GcodeSubmissionError, "not approved"):
            submit(SimpleNamespace(),user,payload)
