from allauth.account.adapter import DefaultAccountAdapter
from allauth.socialaccount.adapter import DefaultSocialAccountAdapter
from django.conf import settings
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
