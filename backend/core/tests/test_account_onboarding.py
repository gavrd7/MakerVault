from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase, override_settings

from core.adapters import MakerVaultAccountAdapter
from core.context_processors import account_capabilities


class AccountOnboardingSettingsTests(SimpleTestCase):
    @override_settings(ALLOW_LOCAL_REGISTRATION=False, EMAIL_HOST="")
    def test_registration_and_email_are_closed_by_default(self):
        self.assertFalse(MakerVaultAccountAdapter().is_open_for_signup(None))
        capabilities = account_capabilities(None)
        self.assertFalse(capabilities["makervault_local_registration"])
        self.assertFalse(capabilities["makervault_email_enabled"])

    @override_settings(ALLOW_LOCAL_REGISTRATION=True, EMAIL_HOST="smtp.example.test")
    def test_registration_and_email_capabilities_can_be_enabled(self):
        self.assertTrue(MakerVaultAccountAdapter().is_open_for_signup(None))
        capabilities = account_capabilities(None)
        self.assertTrue(capabilities["makervault_local_registration"])
        self.assertTrue(capabilities["makervault_email_enabled"])


class AccountOnboardingApiTests(TestCase):
    def setUp(self):
        self.admin = get_user_model().objects.create_superuser(
            username="admin",
            email="admin@example.test",
            password="a-strong-test-password",
        )
        self.client.force_login(self.admin)

    @override_settings(
        ALLOW_LOCAL_REGISTRATION=True,
        EMAIL_HOST="smtp.example.test",
        EMAIL_PORT=587,
        EMAIL_USE_TLS=True,
        EMAIL_USE_SSL=False,
        DEFAULT_FROM_EMAIL="MakerVault <maker@example.test>",
    )
    def test_status_reports_signup_and_smtp_without_credentials(self):
        response = self.client.get("/api/settings/account-onboarding/")
        self.assertEqual(response.status_code, 200, response.content)
        payload = response.json()["settings"]
        self.assertTrue(payload["local_registration_enabled"])
        self.assertTrue(payload["password_reset_available"])
        self.assertEqual(payload["signup_url"], "/accounts/signup/")
        self.assertEqual(payload["password_reset_url"], "/accounts/password/reset/")
        self.assertEqual(payload["smtp"]["host"], "smtp.example.test")
        self.assertEqual(payload["smtp"]["transport"], "STARTTLS")
        self.assertEqual(set(payload["smtp"]), {"host", "port", "transport", "from_email"})

    @override_settings(
        EMAIL_HOST="smtp.example.test",
        EMAIL_PORT=465,
        EMAIL_USE_TLS=False,
        EMAIL_USE_SSL=True,
        DEFAULT_FROM_EMAIL="MakerVault <maker@example.test>",
    )
    @patch("core.api_views.send_mail")
    def test_superuser_can_send_smtp_test_to_own_email(self, send_mail):
        response = self.client.post(
            "/api/settings/account-onboarding/",
            {},
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200, response.content)
        self.assertTrue(response.json()["sent"])
        send_mail.assert_called_once()
        self.assertEqual(send_mail.call_args.kwargs["recipient_list"], ["admin@example.test"])

    @override_settings(EMAIL_HOST="")
    @patch("core.api_views.send_mail")
    def test_smtp_test_fails_closed_when_email_is_disabled(self, send_mail):
        response = self.client.post(
            "/api/settings/account-onboarding/",
            {},
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 409)
        send_mail.assert_not_called()


    @override_settings(
        ALLOW_LOCAL_REGISTRATION=True,
        EMAIL_HOST="smtp.example.test",
        STORAGES={
            "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
            "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
        },
    )
    def test_account_entry_pages_use_makervault_logo(self):
        self.client.logout()
        for url in (
            "/accounts/login/",
            "/accounts/signup/",
            "/accounts/password/reset/",
        ):
            response = self.client.get(url)
            self.assertEqual(response.status_code, 200, url)
            self.assertContains(response, "makervault-logo.jpg")
            self.assertContains(response, 'alt="MakerVault"')

    @override_settings(EMAIL_HOST="smtp.example.test")
    def test_non_superuser_cannot_read_onboarding_settings(self):
        user = get_user_model().objects.create_user(
            username="viewer",
            email="viewer@example.test",
            password="another-strong-password",
        )
        self.client.force_login(user)
        response = self.client.get("/api/settings/account-onboarding/")
        self.assertEqual(response.status_code, 403)
