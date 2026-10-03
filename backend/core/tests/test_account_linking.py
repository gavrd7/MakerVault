from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse

from allauth.socialaccount.models import SocialAccount

from core.adapters import MakerVaultSocialAccountAdapter


class AccountLinkingTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="link-user",
            email="link@example.com",
            password="a-strong-test-password-123",
        )

    @__import__("django.test").test.override_settings(
        STORAGES={
            "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
            "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
        },
    )
    def test_connections_page_explains_sign_in_methods(self):
        self.client.force_login(self.user)
        response = self.client.get(reverse("socialaccount_connections"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Sign-in methods")
        self.assertContains(response, "does not create, merge or move workshop data")
        self.assertContains(response, "No external identity is linked yet")

    def test_disconnect_allowed_when_local_password_remains(self):
        account = SocialAccount.objects.create(
            user=self.user,
            provider="openid_connect",
            uid="oidc-user-1",
        )
        MakerVaultSocialAccountAdapter().validate_disconnect(account, [account])

    def test_disconnect_blocked_when_it_would_remove_last_sign_in_method(self):
        self.user.set_unusable_password()
        self.user.save(update_fields=["password"])
        account = SocialAccount.objects.create(
            user=self.user,
            provider="openid_connect",
            uid="oidc-user-1",
        )
        with self.assertRaisesMessage(
            ValidationError,
            "Add a local password or another sign-in connection",
        ):
            MakerVaultSocialAccountAdapter().validate_disconnect(account, [account])

    def test_disconnect_allowed_when_another_external_identity_remains(self):
        self.user.set_unusable_password()
        self.user.save(update_fields=["password"])
        first = SocialAccount.objects.create(
            user=self.user,
            provider="openid_connect",
            uid="oidc-user-1",
        )
        second = SocialAccount.objects.create(
            user=self.user,
            provider="openid_connect",
            uid="oidc-user-2",
        )
        MakerVaultSocialAccountAdapter().validate_disconnect(first, [first, second])
