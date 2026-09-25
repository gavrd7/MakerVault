from django.urls import path
from . import api_views

urlpatterns = [
    path("dashboard/", api_views.dashboard, name="api-dashboard"),
    path("inventory/", api_views.inventory, name="api-inventory"),
    path("config/", api_views.public_config, name="api-config"),
]
