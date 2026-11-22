"""Bambu Studio G-code follows standard confirmed printer submission gates."""
from types import SimpleNamespace
from unittest.mock import patch
import uuid

from django.test import SimpleTestCase
from core.printer_gcode_submission import submit, GcodeSubmissionError


class BambuPrinterSubmissionContractTests(SimpleTestCase):
    @patch("core.printer_gcode_submission.FileAsset.objects.filter")
    def test_bambu_output_uses_standard_upload_size_gate(self, find_asset):
        # The generic limit is deliberately tested before any printer
        # network calls; there must be no Bambu-specific opt-in / beta guard.
        user = SimpleNamespace(pk=uuid.uuid4())
        asset = SimpleNamespace(
            pk=uuid.uuid4(), metadata={
                "extension": ".gcode", "generated_by": "makervault-slicer",
                "engine": "bambustudio",
            }, file=SimpleNamespace(size=65 * 1024 * 1024),
        )
        find_asset.return_value.first.return_value = asset
        for action in ("upload", "print"):
            with self.subTest(action=action):
                payload = {
                    "confirmed": True, "source": "makervault", "action": action,
                    "request_id": str(uuid.uuid4()),
                    "file_asset_id": str(asset.pk),
                }
                with self.assertRaisesRegex(GcodeSubmissionError, "64 MiB"):
                    submit(SimpleNamespace(), user, payload)

    @patch("core.printer_gcode_submission.FileAsset.objects.filter")
    def test_bambu_still_requires_explicit_standard_confirmation(self, lookup):
        asset = SimpleNamespace(pk=uuid.uuid4(), metadata={
            "extension": ".gcode", "generated_by": "makervault-slicer",
            "engine": "bambustudio",
        })
        lookup.return_value.first.return_value = asset
        with self.assertRaisesRegex(GcodeSubmissionError, "Confirm"):
            submit(SimpleNamespace(), SimpleNamespace(pk=uuid.uuid4()), {
                "confirmed": False, "source": "makervault", "action": "print",
                "file_asset_id": str(asset.pk), "request_id": str(uuid.uuid4()),
            })
