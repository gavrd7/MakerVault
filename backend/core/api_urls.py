from django.urls import path
from . import api_views

urlpatterns = [
    path("dashboard/", api_views.dashboard, name="api-dashboard"),
    path("inventory/", api_views.inventory, name="api-inventory"),
    path("inventory/<uuid:item_id>/", api_views.inventory_detail, name="api-inventory-detail"),
    path("boards/", api_views.boards, name="api-boards"),
    path("boards/<uuid:board_id>/", api_views.board_detail, name="api-board-detail"),
    path("boards/<uuid:board_id>/image/", api_views.board_image, name="api-board-image"),
    path("components/", api_views.components, name="api-components"),
    path("components/<uuid:component_id>/", api_views.component_detail, name="api-component-detail"),
    path("components/<uuid:component_id>/image/", api_views.component_image, name="api-component-image"),
    path("projects/", api_views.projects_lookup, name="api-projects"),
    path("import/board/preview/", api_views.import_board_preview, name="api-import-board-preview"),
    path("import/board/commit/", api_views.import_board_commit, name="api-import-board-commit"),
    path("config/", api_views.public_config, name="api-config"),
]
