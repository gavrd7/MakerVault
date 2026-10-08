from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings


@override_settings(STORAGES={
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
})
class EmbeddedAccountFrameTests(TestCase):
    def setUp(self):
        self.admin = get_user_model().objects.create_superuser(
            username="frame-admin", email="admin@example.test", password="secure-test-password"
        )
        self.client.force_login(self.admin)

    def test_authenticated_account_management_allows_only_same_origin_embedding(self):
        response = self.client.get("/accounts/2fa/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["X-Frame-Options"], "SAMEORIGIN")
        self.assertContains(response, "maker-embedded-account")

    def test_oidc_admin_can_be_embedded_same_origin(self):
        response = self.client.get("/accounts/security/oidc/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["X-Frame-Options"], "SAMEORIGIN")

    def test_other_app_pages_retain_deny_frame_policy(self):
        response = self.client.get("/api/config/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["X-Frame-Options"], "DENY")

    def test_anonymous_account_login_keeps_default_protection(self):
        self.client.logout()
        response = self.client.get("/accounts/login/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["X-Frame-Options"], "DENY")
