"""Engine installation UI must not become a remote shell or package manager."""
import os
from unittest.mock import patch
from django.contrib.auth import get_user_model
from django.test import TestCase
from core.models import SlicerEngineOperation


class EngineManagementAPITests(TestCase):
    endpoint = "/api/printing/slicer/engines/operations/"

    @classmethod
    def setUpTestData(cls):
        User = get_user_model()
        cls.admin = User.objects.create_superuser(
            username="engineadmin", email="engines@example.invalid", password="test-password")
        cls.user = User.objects.create_user(
            username="engineuser", password="test-password")

    def test_requires_authentication_and_superuser(self):
        response = self.client.get(self.endpoint)
        self.assertIn(response.status_code, (302, 401, 403))
        self.client.force_login(self.user)
        self.assertEqual(self.client.get(self.endpoint).status_code, 200)
        self.assertTrue(self.client.get(self.endpoint).json()["can_manage"])

    def test_team_restriction_is_optional_and_disabled_by_default(self):
        from core.models import SlicerEngineAccessSettings
        self.client.force_login(self.user)
        self.assertTrue(self.client.get(self.endpoint).json()["can_manage"])
        settings = SlicerEngineAccessSettings.objects.create(
            restrict_engine_management_to_admins=True)
        response = self.client.get(self.endpoint)
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.json()["can_manage"])
        self.assertEqual(self.client.post(self.endpoint, data={},
                         content_type="application/json").status_code, 403)
        self.client.force_login(self.admin)
        self.assertTrue(self.client.get(self.endpoint).json()["can_manage"])
        settings.restrict_engine_management_to_admins = False
        settings.save()
        self.client.force_login(self.user)
        self.assertTrue(self.client.get(self.endpoint).json()["can_manage"])

    def test_empty_approved_catalogue_does_not_advertise_install(self):
        self.client.force_login(self.admin)
        response = self.client.get(self.endpoint)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["approved_releases"], [])
        self.assertFalse(response.json()["installation_available"])
        self.assertFalse(response.json()["host_updater_connected"])

    def test_rejects_unapproved_url_path_and_digest_requests(self):
        self.client.force_login(self.admin)
        for data in (
            {"engine": "crealityprint", "version": "1", "action": "install",
             "release_sha256": "0" * 64},
            {"engine": "../crealityprint", "version": "1", "action": "update",
             "release_sha256": "0" * 64},
            {"engine": "orcaslicer", "version": "2.5.0", "action": "install",
             "release_sha256": "0" * 64, "url": "https://evil.invalid/tool"},
            {"engine": "orcaslicer", "version": "2.5.0", "action": "run",
             "release_sha256": "0" * 64},
        ):
            with self.subTest(data=data):
                response = self.client.post(self.endpoint, data=data,
                                            content_type="application/json")
                self.assertEqual(response.status_code, 400)
        self.assertFalse(SlicerEngineOperation.objects.exists())

    @patch.dict(os.environ, {"MAKERVAULT_SLICER_HOST_UPDATER_ENABLED": "1"})
    def test_only_curated_release_is_queued_and_competing_operations_blocked(self):
        release = {"engine": "crealityprint", "version": "7.0.1",
                   "binary_sha256": "a" * 64, "bundle_sha256": "b" * 64,
                   "bundle_url": "https://example.invalid/reviewed-package.tar.gz",
                   "architecture": "linux/amd64", "notes": "Reviewed",
                   "adapter_validated": True}
        self.client.force_login(self.user)
        with patch("core.slicer_engine_releases.APPROVED_RELEASES", (release,)):
            listing = self.client.get(self.endpoint).json()
            self.assertTrue(listing["installation_available"])
            payload = {"engine": "crealityprint", "version": "7.0.1",
                       "action": "install", "release_sha256": "b" * 64}
            first = self.client.post(self.endpoint, data=payload,
                                     content_type="application/json")
            self.assertEqual(first.status_code, 202, first.content)
            self.assertEqual(first.json()["operation"]["status"], "queued")
            self.assertEqual(self.client.post(self.endpoint, data=payload,
                             content_type="application/json").status_code, 409)
            self.assertEqual(SlicerEngineOperation.objects.count(), 1)

    def test_release_validation_fails_closed(self):
        from core.slicer_engine_releases import validated_releases
        with patch("core.slicer_engine_releases.APPROVED_RELEASES", ({
            "engine": "crealityprint", "version": "../", "bundle_url": "http://example",
        },)):
            with self.assertRaises(ValueError):
                validated_releases()
