import hashlib
import json
from unittest.mock import patch
from django.contrib.auth import get_user_model
from django.core.files.base import ContentFile
from django.test import TestCase, SimpleTestCase
from core.models import FileAsset, SlicerProfile
from core.slicer_approval import _approved_gcode, approve_profiles_for_worker, fixture_stl
from core.slicer_execution import SlicerExecutionError
from core.slicer_native_resolution import resolved_native_profile
from core.slicer_profiles import SlicerProfileError


class FixtureTests(SimpleTestCase):
    def test_real_extrusion_required_for_approval(self):
        self.assertIn(b"facet normal", fixture_stl())
        with self.assertRaises(SlicerExecutionError):
            _approved_gcode(b"; no gcode\n" * 20)
        data = b"; mock verified fixture (unit test)\nG1 X1 Y1 E0.02 F900\n" * 2
        self.assertEqual(_approved_gcode(data), hashlib.sha256(data).hexdigest())


class NativeApprovalTests(TestCase):
    def setUp(self):
        self.owner = get_user_model().objects.create_user(username="native-owner", password="secret")
        self.profiles = {}
        for kind in ("printer", "filament", "process"):
            raw = json.dumps({"name": "Fixture " + kind, "type": "machine" if kind == "printer" else kind,
                              "layer_height": "0.2"}).encode()
            asset = FileAsset(owner=self.owner, name="Fixture " + kind, category="source",
                              metadata={"extension": ".json", "original_name": kind + ".json"})
            asset.file = ContentFile(raw, name=kind + ".json")
            asset.save()
            self.profiles[kind] = SlicerProfile.objects.create(
                owner=self.owner, file_asset=asset, engine="crealityprint",
                engine_version="7.3.0", kind=kind, name="Fixture " + kind,
                content_sha256=hashlib.sha256(raw).hexdigest(), status="candidate",
            )
        self.installed = {"crealityprint": {
            "version": "7.3.0", "image_digest": "sha256:" + "a" * 64,
            "binary_sha256": "b" * 64, "verified": True, "enabled": True,
        }}

    @patch("core.slicer_approval.run_remote_job")
    @patch("core.slicer_approval.verified_installation")
    def test_real_fixture_receipt_verifies_only_matching_trio(self, verified, worker):
        verified.return_value = self.installed
        worker.return_value = b"; generated\nG1 X1 Y1 E0.2 F900\n" * 2
        result = approve_profiles_for_worker(
            owner=self.owner, engine="crealityprint", version="7.3.0",
            profile_ids={kind: str(row.pk) for kind, row in self.profiles.items()},
        )
        self.assertEqual(result["engine"], "crealityprint")
        self.assertEqual(worker.call_args.kwargs["timeout_seconds"], 95)
        for row in self.profiles.values():
            row.refresh_from_db()
            self.assertEqual(row.status, "verified")
            self.assertEqual(row.verification_evidence["engine_binary_sha256"], "b" * 64)
        self.assertEqual(len(set(row.verification_evidence["receipt_sha256"]
                                 for row in self.profiles.values())), 1)

    @patch("core.slicer_approval.run_remote_job")
    @patch("core.slicer_approval.verified_installation")
    def test_unverified_gcode_does_not_approve_profiles(self, verified, worker):
        verified.return_value = self.installed
        worker.return_value = b"; comment-only\n" * 5
        with self.assertRaises(SlicerExecutionError):
            approve_profiles_for_worker(
                owner=self.owner, engine="crealityprint", version="7.3.0",
                profile_ids={kind: str(row.pk) for kind, row in self.profiles.items()},
            )
        self.assertFalse(SlicerProfile.objects.filter(status="verified").exists())

    def test_parent_is_resolved_only_within_engine_and_version(self):
        printer = self.profiles["printer"]
        raw = json.dumps({"name": printer.name, "inherits": "Base",
                          "nozzle_diameter": "0.4"}).encode()
        printer.file_asset.file.save("custom.json", ContentFile(raw))
        printer.content_sha256 = hashlib.sha256(raw).hexdigest()
        printer.save(update_fields=["content_sha256"])
        with self.assertRaisesRegex(SlicerProfileError, "missing"):
            resolved_native_profile(printer)
        source = FileAsset(owner=self.owner, name="Base", category="source",
                           metadata={"extension": ".json"})
        base = b'{"name":"Base","bed_shape":"0x0,220x0,220x220,0x220"}'
        source.file = ContentFile(base, name="base.json")
        source.save()
        SlicerProfile.objects.create(
            owner=self.owner, file_asset=source, engine="crealityprint",
            engine_version="7.3.0", kind="printer", name="Base",
            content_sha256=hashlib.sha256(base).hexdigest(),
        )
        resolved = json.loads(resolved_native_profile(printer))
        self.assertEqual(resolved["bed_shape"], "0x0,220x0,220x220,0x220")
        self.assertEqual(resolved["nozzle_diameter"], "0.4")
        self.assertNotIn("inherits", resolved)
