from django.contrib import admin
from django.contrib.admin.views.decorators import staff_member_required
from django.urls import include, path
from core import views

# Do not allow Django admin's standalone password login to bypass the allauth/MFA flow.
admin.site.login = staff_member_required(admin.site.login, login_url="/accounts/login/")

urlpatterns = [
    path("admin/", admin.site.urls),
    path("accounts/", include("allauth.urls")),
    path("api/", include("core.api_urls")),
    path("healthz/", views.healthz, name="healthz"),
    path("media/<path:path>", views.media_file, name="media-file"),
    path("", views.app_shell, name="app-shell"),
]
