from django.conf import settings
from django.contrib import messages
from django.contrib.admin.views.decorators import staff_member_required
from django.contrib.sites.shortcuts import get_current_site
from django.http import Http404
from django.shortcuts import redirect, render
from django.views.decorators.http import require_http_methods

from allauth.socialaccount.models import SocialApp

from .forms import OIDCProviderForm


def _oidc_apps():
    return SocialApp.objects.filter(provider="openid_connect").order_by("name", "provider_id")


def _callback_uri(request, provider_id):
    return request.build_absolute_uri(f"/accounts/oidc/{provider_id}/login/callback/")


def _env_provider(request):
    if not settings.OIDC_ENABLED:
        return None
    provider_id = getattr(settings, "OIDC_ENV_PROVIDER_ID", "oidc")
    server_url = getattr(settings, "OIDC_ENV_SERVER_URL", "")
    client_id = getattr(settings, "OIDC_ENV_CLIENT_ID", "")
    if not (server_url and client_id):
        return None
    return {
        "name": getattr(settings, "OIDC_ENV_PROVIDER_NAME", "OpenID Connect"),
        "provider_id": provider_id,
        "server_url": server_url,
        "client_id": client_id,
        "callback_uri": _callback_uri(request, provider_id),
        "auto_signup": settings.OIDC_AUTO_SIGNUP,
    }


@staff_member_required(login_url="/accounts/login/")
@require_http_methods(["GET"])
def oidc_provider_list(request):
    site = get_current_site(request)
    providers = []
    for app in _oidc_apps():
        cfg = app.settings or {}
        providers.append({
            "id": app.pk,
            "name": app.name,
            "provider_id": app.provider_id,
            "server_url": cfg.get("server_url", ""),
            "client_id": app.client_id,
            "enabled": app.sites.filter(pk=site.pk).exists(),
            "pkce": cfg.get("oauth_pkce_enabled", True),
            "fetch_userinfo": cfg.get("fetch_userinfo", True),
            "auto_signup": cfg.get("makervault_auto_signup", True),
            "callback_uri": _callback_uri(request, app.provider_id),
        })
    return render(request, "core/oidc_provider_list.html", {
        "providers": providers,
        "env_provider": _env_provider(request),
    })


@staff_member_required(login_url="/accounts/login/")
@require_http_methods(["GET", "POST"])
def oidc_provider_create(request):
    site = get_current_site(request)
    form = OIDCProviderForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        app = SocialApp(
            provider="openid_connect",
            provider_id=form.cleaned_data["provider_id"],
            name=form.cleaned_data["name"],
            client_id=form.cleaned_data["client_id"],
            secret=form.cleaned_data["client_secret"],
            settings={
                "server_url": form.cleaned_data["server_url"],
                "fetch_userinfo": form.cleaned_data["fetch_userinfo"],
                "oauth_pkce_enabled": form.cleaned_data["pkce"],
                "makervault_auto_signup": form.cleaned_data["auto_signup"],
            },
        )
        app.save()
        if form.cleaned_data["enabled"]:
            app.sites.add(site)
        messages.success(request, f"OIDC provider {app.name} was created.")
        return redirect("oidc-provider-list")
    return render(request, "core/oidc_provider_form.html", {
        "form": form,
        "mode": "create",
        "callback_uri": request.build_absolute_uri("/accounts/oidc/<provider-id>/login/callback/"),
    })


@staff_member_required(login_url="/accounts/login/")
@require_http_methods(["GET", "POST"])
def oidc_provider_edit(request, app_id):
    site = get_current_site(request)
    app = SocialApp.objects.filter(pk=app_id, provider="openid_connect").first()
    if not app:
        raise Http404
    initial = {"enabled": app.sites.filter(pk=site.pk).exists()}
    form = OIDCProviderForm(request.POST or None, instance=app, initial=initial)
    if request.method == "POST" and form.is_valid():
        app.name = form.cleaned_data["name"]
        app.provider_id = form.cleaned_data["provider_id"]
        app.client_id = form.cleaned_data["client_id"]
        if form.cleaned_data["client_secret"]:
            app.secret = form.cleaned_data["client_secret"]
        app.settings = {
            "server_url": form.cleaned_data["server_url"],
            "fetch_userinfo": form.cleaned_data["fetch_userinfo"],
            "oauth_pkce_enabled": form.cleaned_data["pkce"],
            "makervault_auto_signup": form.cleaned_data["auto_signup"],
        }
        app.save()
        if form.cleaned_data["enabled"]:
            app.sites.add(site)
        else:
            app.sites.remove(site)
        messages.success(request, f"OIDC provider {app.name} was updated.")
        return redirect("oidc-provider-list")
    return render(request, "core/oidc_provider_form.html", {
        "form": form,
        "mode": "edit",
        "provider": app,
        "callback_uri": _callback_uri(request, app.provider_id),
    })


@staff_member_required(login_url="/accounts/login/")
@require_http_methods(["POST"])
def oidc_provider_delete(request, app_id):
    app = SocialApp.objects.filter(pk=app_id, provider="openid_connect").first()
    if not app:
        raise Http404
    name = app.name
    app.delete()
    messages.success(request, f"OIDC provider {name} was removed.")
    return redirect("oidc-provider-list")
