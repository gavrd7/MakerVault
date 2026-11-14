"""Candidate native profiles are admitted without manual approval, but not blindly."""
from types import SimpleNamespace
from unittest.mock import patch
from django.test import SimpleTestCase
from core.slicer_execution import _check_profile_integrity, SlicerExecutionError


class CandidateProfileAdmissionTests(SimpleTestCase):
    def setUp(self):
        self.profile = SimpleNamespace(
            owner_id=7, engine="orcaslicer", engine_version="2.4.2",
            kind="filament", name="Generic PLA", status="candidate",
            content_sha256="a" * 64, file_asset=SimpleNamespace(),
        )
        self.job = SimpleNamespace(
            owner_id=7, engine="orcaslicer", engine_version="2.4.2",
            filament_preset="Generic PLA",
        )

    @patch("core.slicer_native_resolution.resolved_native_profile", return_value=b'{}')
    @patch("core.slicer_profiles.inspect_native_profile")
    def test_unapproved_profile_admitted_when_intact(self, inspection, resolve):
        inspection.return_value = {"sha256": "a" * 64}
        _check_profile_integrity(self.profile, self.job, "filament")
        inspection.assert_called_once()
        resolve.assert_called_once_with(self.profile)

    @patch("core.slicer_profiles.inspect_native_profile")
    def test_modified_profile_rejected(self, inspection):
        inspection.return_value = {"sha256": "b" * 64}
        with self.assertRaisesRegex(SlicerExecutionError, "contents changed"):
            _check_profile_integrity(self.profile, self.job, "filament")

    @patch("core.slicer_native_resolution.resolved_native_profile")
    @patch("core.slicer_profiles.inspect_native_profile")
    def test_missing_parent_chain_rejected(self, inspection, resolve):
        from core.slicer_profiles import SlicerProfileError
        inspection.return_value = {"sha256": "a" * 64}
        resolve.side_effect = SlicerProfileError("Missing parent")
        with self.assertRaisesRegex(SlicerExecutionError, "parent presets"):
            _check_profile_integrity(self.profile, self.job, "filament")
