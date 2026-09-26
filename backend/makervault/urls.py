from django.contrib import admin
from django.contrib.admin.views.decorators import staff_member_required
from django.urls import include, path
from core import views

# Do not allow Django admin's standalone password login to bypass the allauth/MFA flow.
admin.site.login = staff_member_required(admin.site.login, login_url="/accounts/login/")

def legal_text(filename):
    from django.conf import settings
    from django.http import HttpResponse, Http404

    path = settings.BASE_DIR.parent / filename
    if not path.is_file():
        raise Http404
    return HttpResponse(path.read_text(encoding="utf-8"), content_type="text/plain; charset=utf-8")


urlpatterns = [
    path("admin/", admin.site.urls),
    path("accounts/", include("allauth.urls")),
    path("api/", include("core.api_urls")),
    path("legal/license/", lambda request: legal_text("LICENSE"), name="legal-license"),
    path("legal/third-party-notices/", lambda request: legal_text("THIRD_PARTY_NOTICES.md"), name="third-party-notices"),
    path("healthz/", views.healthz, name="healthz"),
    path("media/<path:path>", views.media_file, name="media-file"),
    path("", views.app_shell, name="app-shell"),
]
