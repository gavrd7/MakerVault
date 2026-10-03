from allauth.account.adapter import DefaultAccountAdapter
from allauth.socialaccount.adapter import DefaultSocialAccountAdapter
from django.conf import settings
from django.core.exceptions import ValidationError
from allauth.socialaccount.models import SocialApp


class MakerVaultAccountAdapter(DefaultAccountAdapter):
    def is_open_for_signup(self, request):
        return bool(settings.ALLOW_LOCAL_REGISTRATION)


class MakerVaultSocialAccountAdapter(DefaultSocialAccountAdapter):
    def is_open_for_signup(self, request, socialaccount):
        # GUI-managed OIDC providers can control auto-provisioning individually.
        provider_id = getattr(socialaccount, "provider", "")
        app = SocialApp.objects.filter(
            provider="openid_connect",
            provider_id=provider_id,
            sites__id=settings.SITE_ID,
        ).first()
        if app:
            return bool((app.settings or {}).get("makervault_auto_signup", True))
        # Environment-backed OIDC retains the global bootstrap setting.
        return bool(settings.OIDC_AUTO_SIGNUP)

    def validate_disconnect(self, account, accounts):
        user = account.user
        remaining = [candidate for candidate in accounts if candidate.pk != account.pk]
        if user.has_usable_password() or remaining:
            return
        raise ValidationError(
            "Add a local password or another sign-in connection before removing your only external sign-in method."
        )
