"""Administrative profile approval must remain opt-in and tied to exact hashes."""
import hashlib
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.files.base import ContentFile
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase

from core.models import FileAsset, SlicerProfile
from core.management.commands.approve_slicer_fixture import _load_receipt


KINDS = ("printer", "filament", "process")


class SlicerFixtureApprovalTests(TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.owner = get_user_model().objects.create_user(username="fixture-owner", password="unused")
        self.version = "2.4.2"
        self.image_digest = "sha256:" + "a" * 64
        self.binary_sha = "b" * 64
        self.profiles = {}
        sha_by_kind = {}
        for kind in KINDS:
            content = json.dumps({"name": "Fixture " + kind, "layer_height": "0.2"}).encode()
            asset = FileAsset(
                owner=self.owner, name=kind + ".json", category="source",
                metadata={"original_name": kind + ".json", "extension": ".json"},
            )
            asset.file = ContentFile(content, name=kind + ".json")
            asset.save()
            self.addCleanup(lambda stored=asset: stored.file.delete(save=False))
            row = SlicerProfile.objects.create(
                owner=self.owner, engine="orcaslicer", engine_version=self.version,
                kind=kind, name="Fixture " + kind, file_asset=asset,
                content_sha256=hashlib.sha256(content).hexdigest(),
            )
            self.profiles[kind] = row
            sha_by_kind[kind] = row.content_sha256
        self.receipt = {
            "engine": "orcaslicer",
            "engine_version": self.version,
            "engine_binary_sha256": self.binary_sha,
            "fixture_sha256": "c" * 64,
            "gcode_sha256": "d" * 64,
            "gcode_bytes": 105,
            "cli_invocation": "verified",
            "approved_for_production": False,
            **{kind + "_profile_sha256": sha for kind, sha in sha_by_kind.items()},
        }
        self.path = Path(self.temp.name) / "receipt.json"
        self.write_receipt()
        self.args = {
            "receipt": str(self.path),
            **{kind + "_profile": str(row.pk) for kind, row in self.profiles.items()},
        }
        self.settings = {
            "MAKERVAULT_SLICER_ENGINE": "orcaslicer",
            "MAKERVAULT_SLICER_EXECUTION_ENABLED": "1",
            "MAKERVAULT_SLICER_WORKER_IMAGE": "example.invalid/slicer@" + self.image_digest,
            "MAKERVAULT_SLICER_ENGINE_IMAGE_DIGEST": self.image_digest,
            "MAKERVAULT_SLICER_ENGINE_BINARY_SHA256": self.binary_sha,
            "MAKERVAULT_SLICER_ENGINE_VERSION": self.version,
        }

    def write_receipt(self):
        self.path.write_text(json.dumps(self.receipt))

    def test_dry_run_does_not_change_profile_state(self):
        call_command("approve_slicer_fixture", **self.args)
        self.assertFalse(SlicerProfile.objects.exclude(status="candidate").exists())

    def test_approval_requires_two_reviews_and_exact_output_hash(self):
        with patch.dict("os.environ", self.settings, clear=True):
            with self.assertRaises(CommandError):
                call_command("approve_slicer_fixture", **self.args, approve=True)
            with self.assertRaises(CommandError):
                call_command(
                    "approve_slicer_fixture", **self.args, approve=True,
                    acknowledge_image_reviewed=True, acknowledge_gcode_reviewed=True,
                    expected_gcode_sha256="0" * 64,
                )
            self.assertFalse(SlicerProfile.objects.exclude(status="candidate").exists())
            call_command(
                "approve_slicer_fixture", **self.args, approve=True,
                acknowledge_image_reviewed=True, acknowledge_gcode_reviewed=True,
                expected_gcode_sha256=self.receipt["gcode_sha256"],
            )
        for profile in self.profiles.values():
            profile.refresh_from_db()
            self.assertEqual(profile.status, "verified")
            self.assertEqual(profile.verification_evidence["image_digest"], self.image_digest)
            self.assertIsNotNone(profile.verified_at)

    def test_changed_profile_or_binary_digest_cannot_be_approved(self):
        self.receipt["filament_profile_sha256"] = "f" * 64
        self.write_receipt()
        with self.assertRaises(CommandError):
            call_command("approve_slicer_fixture", **self.args)
        self.receipt["filament_profile_sha256"] = self.profiles["filament"].content_sha256
        self.write_receipt()
        with patch.dict("os.environ", {**self.settings, "MAKERVAULT_SLICER_ENGINE_BINARY_SHA256": "f" * 64}, clear=True):
            with self.assertRaises(CommandError):
                call_command(
                    "approve_slicer_fixture", **self.args, approve=True,
                    acknowledge_image_reviewed=True, acknowledge_gcode_reviewed=True,
                    expected_gcode_sha256=self.receipt["gcode_sha256"],
                )

    def test_receipt_cannot_self_approve(self):
        self.receipt["approved_for_production"] = True
        self.write_receipt()
        with self.assertRaises(CommandError):
            _load_receipt(self.path)
