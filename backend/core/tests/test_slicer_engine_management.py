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

    def test_disabled_installer_never_advertises_install(self):
        self.client.force_login(self.user)
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
                expected = 503 if data.get("engine") == "crealityprint" and set(data) == {
                    "engine", "version", "action", "release_sha256"} else 400
                self.assertEqual(response.status_code, expected)
        self.assertFalse(SlicerEngineOperation.objects.exists())

    @patch.dict(os.environ, {"MAKERVAULT_SLICER_HOST_UPDATER_ENABLED": "1"})
    def test_signed_in_user_can_queue_official_install_and_competing_blocked(self):
        import uuid
        operation_id = str(uuid.uuid4())
        release = {"engine": "crealityprint", "version": "7.3.1",
                   "bundle_sha256": "b" * 64, "binary_sha256": "b" * 64,
                   "architecture": "linux/amd64", "notes": "Creality Print",
                   "asset_size": 191511032}
        def installer(method, path, payload=None):
            if path == "/catalog":
                return {"releases": [release]}
            if path == "/status":
                return {"operations": []}
            if path == "/install":
                assert payload == {
                    "engine": "crealityprint", "version": "7.3.1",
                    "bundle_sha256": "b" * 64,
                }
                return {"operation": {
                    "id": operation_id, "engine": "crealityprint",
                    "version": "7.3.1", "status": "queued",
                }}
            raise AssertionError("Unexpected installer request")
        self.client.force_login(self.user)
        with patch("core.slicer_engine_management_api.installer_request", side_effect=installer):
            listing = self.client.get(self.endpoint).json()
            self.assertTrue(listing["installation_available"])
            payload = {"engine": "crealityprint", "version": "7.3.1",
                       "action": "install", "release_sha256": "b" * 64}
            first = self.client.post(self.endpoint, data=payload,
                                     content_type="application/json")
            self.assertEqual(first.status_code, 202, first.content)
            self.assertEqual(first.json()["operation"]["status"], "queued")
            self.assertEqual(self.client.post(self.endpoint, data=payload,
                             content_type="application/json").status_code, 409)
            self.assertEqual(SlicerEngineOperation.objects.count(), 1)

    @patch.dict(os.environ, {"MAKERVAULT_SLICER_HOST_UPDATER_ENABLED": "1"})
    def test_status_progress_is_copied_from_installer(self):
        import uuid
        from core.models import SlicerEngineOperation
        record = SlicerEngineOperation.objects.create(
            requested_by=self.user, engine="crealityprint", version="7.3.1",
            action="install", release_sha256="a" * 64)
        def installer(method, path, payload=None):
            if path == "/catalog":
                return {"releases": []}
            return {"operations": [{
                "id": str(record.pk), "engine": "crealityprint",
                "status": "completed", "progress": 100,
                "message": "Installed and activated",
            }]}
        self.client.force_login(self.user)
        with patch("core.slicer_engine_management_api.installer_request", side_effect=installer):
            response = self.client.get(self.endpoint)
        self.assertEqual(response.status_code, 200, response.content)
        record.refresh_from_db()
        self.assertEqual(record.status, "completed")
        self.assertEqual(record.progress, 100)
        self.assertIsNotNone(record.completed_at)

    @patch.dict(os.environ, {"MAKERVAULT_SLICER_HOST_UPDATER_ENABLED": "1"})
    def test_installed_versions_are_visible_without_new_release_catalogue(self):
        self.client.force_login(self.user)
        def installer(method, path, payload=None):
            if path == "/status":
                return {"operations": [], "installed_versions": {
                    "orcaslicer": [
                        {"version": "2.5.0", "active": True},
                        {"version": "2.4.2", "active": False},
                    ]}}
            if path == "/catalog":
                return {"releases": []}
            raise AssertionError(path)
        with patch("core.slicer_engine_management_api.installer_request", side_effect=installer):
            result = self.client.get(self.endpoint).json()
        self.assertEqual(len(result["installed_versions"]["orcaslicer"]), 2)
        self.assertTrue(result["host_updater_connected"])
        self.assertFalse(result["installation_available"])

    @patch.dict(os.environ, {"MAKERVAULT_SLICER_HOST_UPDATER_ENABLED": "1"})
    def test_any_signed_in_user_can_switch_and_uninstall_unless_restricted(self):
        import uuid
        from core.models import SlicerEngineAccessSettings
        self.client.force_login(self.user)
        calls = []
        def installer(method, path, payload=None):
            calls.append((method, path, payload))
            if path == "/status":
                return {"operations": []}
            if path == "/catalog":
                return {"releases": []}
            if path in {"/activate", "/uninstall"}:
                return {"operation": {"id": str(uuid.uuid4()),
                        "engine": payload["engine"], "version": payload["version"],
                        "status": "queued"}}
            raise AssertionError(path)
        switch = {"engine": "orcaslicer", "version": "2.4.2",
                  "action": "activate", "release_sha256": "0" * 64}
        remove = {"engine": "orcaslicer", "version": "all",
                  "action": "uninstall", "release_sha256": "0" * 64}
        with patch("core.slicer_engine_management_api.installer_request", side_effect=installer):
            response = self.client.post(self.endpoint, data=switch, content_type="application/json")
            self.assertEqual(response.status_code, 202, response.content)
            self.assertIn(("POST", "/activate",
                           {"engine": "orcaslicer", "version": "2.4.2"}), calls)
            self.assertEqual(self.client.post(self.endpoint, data=remove,
                             content_type="application/json").status_code, 409)
            # A completed operation no longer blocks subsequent user changes.
            SlicerEngineOperation.objects.update(status="completed")
            response = self.client.post(self.endpoint, data=remove, content_type="application/json")
            self.assertEqual(response.status_code, 202, response.content)
            self.assertIn(("POST", "/uninstall", {"engine": "orcaslicer", "version": "all"}), calls)
            SlicerEngineAccessSettings.objects.create(
                restrict_engine_management_to_admins=True)
            self.assertEqual(self.client.post(self.endpoint, data=remove,
                             content_type="application/json").status_code, 403)

    @patch.dict(os.environ, {"MAKERVAULT_SLICER_HOST_UPDATER_ENABLED": "1"})
    def test_engine_lifecycle_rejects_untrusted_request_forms(self):
        self.client.force_login(self.user)
        for mutation in (
            {"engine": "orcaslicer", "version": "all",
             "action": "activate", "release_sha256": "1" * 64},
            {"engine": "../orcaslicer", "version": "all",
             "action": "uninstall", "release_sha256": "0" * 64},
            {"engine": "orcaslicer", "version": "2.5.0",
             "action": "uninstall", "release_sha256": "0" * 64},
        ):
            with self.subTest(mutation=mutation):
                self.assertEqual(self.client.post(
                    self.endpoint, data=mutation,
                    content_type="application/json").status_code, 400)

    def test_release_validation_fails_closed(self):
        from core.slicer_engine_releases import validated_releases
        with patch("core.slicer_engine_releases.APPROVED_RELEASES", ({
            "engine": "crealityprint", "version": "../", "bundle_url": "http://example",
        },)):
            with self.assertRaises(ValueError):
                validated_releases()
