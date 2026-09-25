from allauth.account.adapter import DefaultAccountAdapter
from allauth.socialaccount.adapter import DefaultSocialAccountAdapter
from django.conf import settings


class MakerVaultAccountAdapter(DefaultAccountAdapter):
    def is_open_for_signup(self, request):
        return bool(settings.ALLOW_LOCAL_REGISTRATION)


class MakerVaultSocialAccountAdapter(DefaultSocialAccountAdapter):
    def is_open_for_signup(self, request, socialaccount):
        # OIDC accounts can be provisioned on first login when explicitly enabled.
        return bool(settings.OIDC_AUTO_SIGNUP)
