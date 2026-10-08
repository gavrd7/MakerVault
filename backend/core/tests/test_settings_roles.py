from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import TestCase

from core.user_admin import assign_user_role, user_role


class MakerVaultRoleTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command("seed_roles", verbosity=0)
        User = get_user_model()
        cls.admin = User.objects.create_superuser("role-admin", "admin@example.test", "test-passphrase")
        cls.supervisor = User.objects.create_user("role-supervisor", "supervisor@example.test", "test-passphrase")
        cls.viewer = User.objects.create_user("role-viewer", "viewer@example.test", "test-passphrase")
        assign_user_role(cls.supervisor, "Supervisor")
        assign_user_role(cls.viewer, "Viewer")

    def test_administrator_can_change_roles_without_touching_user_data(self):
        self.client.force_login(self.admin)
        response = self.client.patch(
            f"/api/settings/users/{self.viewer.pk}/",
            data='{"role":"User"}',
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200, response.content)
        self.viewer.refresh_from_db()
        self.assertEqual(user_role(self.viewer), "User")
        self.assertFalse(self.viewer.is_staff)
        self.assertFalse(self.viewer.is_superuser)

        response = self.client.patch(
            f"/api/settings/users/{self.viewer.pk}/",
            data='{"role":"Supervisor"}',
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200, response.content)
        self.viewer.refresh_from_db()
        self.assertEqual(user_role(self.viewer), "Supervisor")
        self.assertFalse(self.viewer.is_staff)

    def test_supervisor_can_update_operational_settings_but_not_admin_or_https(self):
        self.client.force_login(self.supervisor)
        config = self.client.get("/api/config/").json()
        self.assertEqual(config["role"], "Supervisor")
        self.assertTrue(config["can_manage_workspace_settings"])
        self.assertEqual(self.client.get("/api/settings/catalogue-maintenance/").status_code, 200)
        self.assertEqual(self.client.get("/api/settings/printing-integrations/").status_code, 200)
        self.assertEqual(self.client.get("/api/settings/users/").status_code, 403)
        self.assertEqual(self.client.get("/api/settings/https/").status_code, 403)
        self.assertEqual(self.client.get("/accounts/security/oidc/").status_code, 302)

    def test_viewer_cannot_access_admin_or_operational_settings(self):
        self.client.force_login(self.viewer)
        config = self.client.get("/api/config/").json()
        self.assertEqual(config["role"], "Viewer")
        self.assertFalse(config["can_manage_workspace_settings"])
        self.assertEqual(self.client.get("/api/settings/catalogue-maintenance/").status_code, 403)
        self.assertEqual(self.client.get("/api/settings/printing-integrations/").status_code, 403)
        self.assertEqual(self.client.get("/api/settings/users/").status_code, 403)

    def test_supervisor_cannot_promote_self_or_others(self):
        self.client.force_login(self.supervisor)
        response = self.client.patch(
            f"/api/settings/users/{self.viewer.pk}/",
            data='{"role":"Admin"}',
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 403)

    def test_admin_cannot_demote_self(self):
        self.client.force_login(self.admin)
        response = self.client.patch(
            f"/api/settings/users/{self.admin.pk}/",
            data='{"role":"Viewer"}',
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 400)
        self.admin.refresh_from_db()
        self.assertTrue(self.admin.is_superuser)
