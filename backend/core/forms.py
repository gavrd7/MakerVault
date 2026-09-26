import re

from django import forms
from django.core.exceptions import ValidationError
from allauth.socialaccount.models import SocialApp


_PROVIDER_ID_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{1,62}$")


class OIDCProviderForm(forms.Form):
    name = forms.CharField(max_length=100, label="Display name")
    provider_id = forms.CharField(
        max_length=63,
        label="Provider ID",
        help_text="Lower-case identifier used in callback/login URLs, e.g. authentik or keycloak.",
    )
    server_url = forms.URLField(
        label="OIDC server / issuer URL",
        help_text="The issuer/base URL advertised by your OpenID Connect provider.",
    )
    client_id = forms.CharField(max_length=191, label="Client ID")
    client_secret = forms.CharField(
        max_length=191,
        label="Client secret",
        widget=forms.PasswordInput(render_value=False),
        required=False,
        help_text="Leave blank while editing to keep the existing secret.",
    )
    fetch_userinfo = forms.BooleanField(label="Fetch UserInfo", required=False, initial=True)
    pkce = forms.BooleanField(label="Use PKCE", required=False, initial=True)
    auto_signup = forms.BooleanField(
        label="Automatically create users on first OIDC login",
        required=False,
        initial=True,
    )
    enabled = forms.BooleanField(label="Enabled", required=False, initial=True)

    def __init__(self, *args, instance=None, **kwargs):
        self.instance = instance
        super().__init__(*args, **kwargs)
        if instance and not self.is_bound:
            cfg = instance.settings or {}
            self.initial.update({
                "name": instance.name,
                "provider_id": instance.provider_id,
                "server_url": cfg.get("server_url", ""),
                "client_id": instance.client_id,
                "fetch_userinfo": cfg.get("fetch_userinfo", True),
                "pkce": cfg.get("oauth_pkce_enabled", True),
                "auto_signup": cfg.get("makervault_auto_signup", True),
            })
        if instance is None:
            self.fields["client_secret"].required = True
            self.fields["client_secret"].help_text = "Required when creating a provider."

    def clean_provider_id(self):
        value = self.cleaned_data["provider_id"].strip().lower()
        if not _PROVIDER_ID_RE.fullmatch(value):
            raise ValidationError("Use lower-case letters, numbers, hyphens or underscores.")
        qs = SocialApp.objects.filter(provider="openid_connect", provider_id=value)
        if self.instance:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise ValidationError("An OIDC provider with this ID already exists.")
        return value

    def clean_server_url(self):
        return self.cleaned_data["server_url"].rstrip("/")
