from django.contrib import admin
from .models import (
    Manufacturer, CatalogSource, CatalogueMaintenanceSettings, BoardModel, BoardCompatibility, ComponentCategory,
    ComponentModel, Project, InventoryItem, InventoryHistory, BOMItem, BOMAllocation, FileAsset, RepositoryLink,
    FilamentProduct, Spool, ExternalSpoolLink, ExternalPrinterLink, PrinterManufacturer, PrinterCatalogModel,
    Printer, PrinterFilamentSlot,
    Model3D, ModelRevision, ModelRevisionAsset, ProductListing, PrintJob, PrintMaterialUsage,
)


@admin.register(CatalogueMaintenanceSettings)
class CatalogueMaintenanceSettingsAdmin(admin.ModelAdmin):
    list_display = ("enabled", "interval_hours", "check_board_data", "check_printer_data", "check_images", "last_run_at", "next_run_at")
    readonly_fields = ("last_run_at", "next_run_at", "last_triggered_by", "created_at", "updated_at")

    def has_add_permission(self, request):
        return not CatalogueMaintenanceSettings.objects.exists()

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(BoardModel)
class BoardModelAdmin(admin.ModelAdmin):
    list_display = ("name", "manufacturer", "family", "variant", "mcu", "wifi", "bluetooth", "zigbee", "thread")
    list_filter = ("family", "wifi", "bluetooth", "zigbee", "thread", "manufacturer")
    search_fields = ("name", "variant", "mcu", "manufacturer__name")
    prepopulated_fields = {}


# The Django admin intentionally exposes shared/reference catalogues only.
# Private user content is administered through ownership-safe MakerVault controls;
# staff status is not a bypass for browsing another user's files or records.
admin.site.register([
    Manufacturer, CatalogSource, BoardCompatibility, ComponentCategory, ComponentModel,
    FilamentProduct, PrinterManufacturer, PrinterCatalogModel, ProductListing,
])

admin.site.site_header = "MakerVault administration"
admin.site.site_title = "MakerVault"
admin.site.index_title = "MakerVault data"
