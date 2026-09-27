from django.contrib import admin
from .models import (
    Manufacturer, CatalogSource, CatalogueMaintenanceSettings, BoardModel, BoardCompatibility, ComponentCategory,
    ComponentModel, Project, InventoryItem, InventoryHistory, BOMItem, BOMAllocation, FileAsset, RepositoryLink,
    FilamentProduct, Spool, ExternalSpoolLink, Printer, PrinterFilamentSlot,
    Model3D, ModelRevision, ModelRevisionAsset, ProductListing, PrintJob,
)


@admin.register(CatalogueMaintenanceSettings)
class CatalogueMaintenanceSettingsAdmin(admin.ModelAdmin):
    list_display = ("enabled", "interval_hours", "check_board_data", "check_images", "last_run_at", "next_run_at")
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


@admin.register(InventoryItem)
class InventoryItemAdmin(admin.ModelAdmin):
    list_display = ("inventory_id", "display_name", "item_type", "quantity", "status", "project", "location")
    list_filter = ("item_type", "status")
    search_fields = ("inventory_id", "custom_name", "board__name", "component__name", "serial_number")


@admin.register(BOMItem)
class BOMItemAdmin(admin.ModelAdmin):
    list_display = ("project", "display_name", "quantity", "unit", "unit_cost", "currency")
    list_filter = ("project", "currency")
    search_fields = ("project__name", "custom_name", "board__name", "component__name")


@admin.register(BOMAllocation)
class BOMAllocationAdmin(admin.ModelAdmin):
    list_display = ("bom_item", "inventory_item", "quantity", "allocated_by", "created_at")
    list_filter = ("bom_item__project", "created_at")
    search_fields = ("bom_item__project__name", "bom_item__custom_name", "inventory_item__inventory_id", "inventory_item__custom_name")
    readonly_fields = ("created_at", "updated_at")


@admin.register(InventoryHistory)
class InventoryHistoryAdmin(admin.ModelAdmin):
    list_display = ("inventory_item", "event_type", "summary", "project", "changed_by", "created_at")
    list_filter = ("event_type", "created_at")
    search_fields = ("inventory_item__inventory_id", "summary", "project__name")
    readonly_fields = ("inventory_item", "event_type", "summary", "changes", "project", "changed_by", "created_at", "updated_at")


@admin.register(Project)
class ProjectAdmin(admin.ModelAdmin):
    list_display = ("name", "status", "updated_at")
    list_filter = ("status",)
    search_fields = ("name", "summary", "description")


admin.site.register([
    Manufacturer, CatalogSource, BoardCompatibility, ComponentCategory, ComponentModel,
    FileAsset, RepositoryLink, FilamentProduct, Spool, ExternalSpoolLink,
    Printer, PrinterFilamentSlot, Model3D, ModelRevision, ModelRevisionAsset,
    ProductListing, PrintJob,
])

admin.site.site_header = "MakerVault administration"
admin.site.site_title = "MakerVault"
admin.site.index_title = "MakerVault data"
