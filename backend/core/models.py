import uuid
from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils.text import slugify
from .validators import validate_maker_file


class TimeStampedModel(models.Model):
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class CatalogueMaintenanceSettings(TimeStampedModel):
    """Singleton schedule for automatic catalogue maintenance."""

    singleton_key = models.PositiveSmallIntegerField(default=1, unique=True, editable=False)
    enabled = models.BooleanField(default=True)
    interval_hours = models.PositiveIntegerField(default=24)
    check_board_data = models.BooleanField(default=True)
    check_printer_data = models.BooleanField(default=True)
    check_images = models.BooleanField(default=True)
    last_run_at = models.DateTimeField(blank=True, null=True)
    next_run_at = models.DateTimeField(blank=True, null=True)
    last_triggered_by = models.CharField(max_length=120, blank=True)

    class Meta:
        verbose_name = "Catalogue maintenance settings"
        verbose_name_plural = "Catalogue maintenance settings"

    def clean(self):
        if not 1 <= int(self.interval_hours) <= 720:
            raise ValidationError({"interval_hours": "Choose an interval between 1 and 720 hours."})

    def save(self, *args, **kwargs):
        self.singleton_key = 1
        super().save(*args, **kwargs)

    def __str__(self):
        return f"Catalogue maintenance every {self.interval_hours}h"


class Manufacturer(TimeStampedModel):
    name = models.CharField(max_length=200, unique=True)
    website = models.URLField(blank=True)
    logo = models.ImageField(upload_to="manufacturers/", blank=True, null=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class CatalogSource(TimeStampedModel):
    SOURCE_TYPES = [
        ("manual", "Manual"), ("espboards", "ESPBoards.dev"), ("spoolmandb", "SpoolmanDB"),
        ("filamentprofiles", "3D Filament Profiles"), ("filamentsdb", "FilamentsDB"),
        ("amazon", "Amazon"), ("aliexpress", "AliExpress"), ("github", "GitHub"),
        ("gitlab", "GitLab"), ("manufacturer", "Manufacturer"), ("generic", "Generic URL"),
    ]
    name = models.CharField(max_length=200)
    source_type = models.CharField(max_length=32, choices=SOURCE_TYPES, default="manual")
    url = models.URLField(blank=True)
    external_id = models.CharField(max_length=255, blank=True)
    last_checked_at = models.DateTimeField(blank=True, null=True)
    raw_metadata = models.JSONField(default=dict, blank=True)

    def __str__(self):
        return self.name


class BoardModel(TimeStampedModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    manufacturer = models.ForeignKey(Manufacturer, on_delete=models.SET_NULL, null=True, blank=True, related_name="boards")
    source = models.ForeignKey(CatalogSource, on_delete=models.SET_NULL, null=True, blank=True, related_name="boards")
    name = models.CharField(max_length=255)
    slug = models.SlugField(max_length=280, unique=True, blank=True)
    family = models.CharField(max_length=120, blank=True)
    variant = models.CharField(max_length=120, blank=True)
    description = models.TextField(blank=True)
    image = models.ImageField(upload_to="boards/catalog/", blank=True, null=True)
    mcu = models.CharField(max_length=120, blank=True)
    architecture = models.CharField(max_length=120, blank=True)
    flash_mb = models.DecimalField(max_digits=8, decimal_places=2, blank=True, null=True)
    psram_mb = models.DecimalField(max_digits=8, decimal_places=2, blank=True, null=True)
    ram_kb = models.DecimalField(max_digits=10, decimal_places=2, blank=True, null=True)
    gpio_count = models.PositiveSmallIntegerField(blank=True, null=True)
    wifi = models.BooleanField(default=False)
    bluetooth = models.BooleanField(default=False)
    zigbee = models.BooleanField(default=False)
    thread = models.BooleanField(default=False)
    usb_connector = models.CharField(max_length=80, blank=True)
    dimensions_mm = models.JSONField(default=dict, blank=True)
    specifications = models.JSONField(default=dict, blank=True)
    pinout = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["manufacturer__name", "name"]
        constraints = [models.UniqueConstraint(fields=["manufacturer", "name", "variant"], name="unique_board_variant")]

    def save(self, *args, **kwargs):
        if not self.slug:
            base = slugify("-".join(filter(None, [self.manufacturer.name if self.manufacturer else "", self.name, self.variant]))) or str(self.id)
            self.slug = base[:270]
        super().save(*args, **kwargs)

    def __str__(self):
        prefix = f"{self.manufacturer} " if self.manufacturer else ""
        return f"{prefix}{self.name}".strip()


class BoardCompatibility(TimeStampedModel):
    SUPPORT = [("full", "Full"), ("partial", "Partial"), ("experimental", "Experimental"), ("unknown", "Unknown"), ("no", "Not supported")]
    board = models.ForeignKey(BoardModel, on_delete=models.CASCADE, related_name="compatibility")
    platform = models.CharField(max_length=80)
    support_level = models.CharField(max_length=20, choices=SUPPORT, default="unknown")
    notes = models.TextField(blank=True)
    config_template = models.TextField(blank=True)
    source_url = models.URLField(blank=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["board", "platform"], name="unique_board_platform")]
        ordering = ["platform"]

    def __str__(self):
        return f"{self.board} / {self.platform}"


class ComponentCategory(TimeStampedModel):
    name = models.CharField(max_length=120)
    slug = models.SlugField(max_length=140, unique=True)
    parent = models.ForeignKey("self", on_delete=models.SET_NULL, null=True, blank=True, related_name="children")

    class Meta:
        verbose_name_plural = "Component categories"
        ordering = ["name"]

    def __str__(self):
        return self.name


class ComponentModel(TimeStampedModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    manufacturer = models.ForeignKey(Manufacturer, on_delete=models.SET_NULL, null=True, blank=True, related_name="components")
    category = models.ForeignKey(ComponentCategory, on_delete=models.SET_NULL, null=True, blank=True, related_name="components")
    source = models.ForeignKey(CatalogSource, on_delete=models.SET_NULL, null=True, blank=True, related_name="components")
    name = models.CharField(max_length=255)
    part_number = models.CharField(max_length=160, blank=True)
    description = models.TextField(blank=True)
    image = models.ImageField(upload_to="components/catalog/", blank=True, null=True)
    specifications = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class Project(TimeStampedModel):
    STATUS = [("idea", "Idea"), ("planning", "Planning"), ("active", "Active"), ("paused", "Paused"), ("complete", "Complete"), ("archived", "Archived")]
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=255)
    slug = models.SlugField(max_length=280, unique=True, blank=True)
    status = models.CharField(max_length=20, choices=STATUS, default="idea")
    summary = models.CharField(max_length=500, blank=True)
    description = models.TextField(blank=True)
    notes = models.TextField(blank=True)
    tags = models.JSONField(default=list, blank=True)
    reference_url = models.URLField(blank=True)
    cover_image = models.ImageField(upload_to="projects/covers/", blank=True, null=True)
    started_on = models.DateField(blank=True, null=True)
    completed_on = models.DateField(blank=True, null=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="makervault_projects")

    class Meta:
        ordering = ["-updated_at"]

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = (slugify(self.name) or str(self.id))[:270]
        super().save(*args, **kwargs)

    def __str__(self):
        return self.name


class InventoryItem(TimeStampedModel):
    ITEM_TYPES = [("board", "Board"), ("component", "Component"), ("tool", "Tool / asset"), ("printed_part", "Printed part"), ("other", "Other")]
    STATUS = [("available", "Available"), ("in_use", "In use"), ("reserved", "Reserved"), ("repair", "Needs repair"), ("retired", "Retired")]
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    inventory_id = models.CharField(max_length=40, unique=True)
    item_type = models.CharField(max_length=20, choices=ITEM_TYPES)
    board = models.ForeignKey(BoardModel, on_delete=models.PROTECT, null=True, blank=True, related_name="inventory_items")
    component = models.ForeignKey(ComponentModel, on_delete=models.PROTECT, null=True, blank=True, related_name="inventory_items")
    custom_name = models.CharField(max_length=255, blank=True)
    quantity = models.DecimalField(max_digits=12, decimal_places=3, default=1)
    status = models.CharField(max_length=20, choices=STATUS, default="available")
    project = models.ForeignKey(Project, on_delete=models.SET_NULL, null=True, blank=True, related_name="inventory_items")
    location = models.CharField(max_length=255, blank=True)
    serial_number = models.CharField(max_length=255, blank=True)
    purchase_price = models.DecimalField(max_digits=12, decimal_places=2, blank=True, null=True)
    currency = models.CharField(max_length=3, default="GBP")
    supplier = models.CharField(max_length=255, blank=True)
    purchase_url = models.URLField(blank=True)
    purchased_on = models.DateField(blank=True, null=True)
    image = models.ImageField(upload_to="inventory/", blank=True, null=True)
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ["inventory_id"]

    def clean(self):
        if self.item_type == "board" and not self.board:
            raise ValidationError({"board": "A board inventory item must reference a board model."})
        if self.item_type == "component" and not self.component:
            raise ValidationError({"component": "A component inventory item must reference a component model."})

    @property
    def display_name(self):
        return self.custom_name or (str(self.board) if self.board else str(self.component) if self.component else self.inventory_id)

    def __str__(self):
        return f"{self.inventory_id} — {self.display_name}"


class InventoryHistory(TimeStampedModel):
    EVENT_TYPES = [
        ("created", "Added to inventory"),
        ("updated", "Updated"),
        ("assigned", "Assigned to project"),
        ("unassigned", "Removed from project"),
        ("status", "Status changed"),
        ("location", "Location changed"),
        ("bom_allocated", "Allocated to BOM"),
        ("bom_released", "Released from BOM"),
    ]
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    inventory_item = models.ForeignKey(
        InventoryItem, on_delete=models.CASCADE, related_name="history"
    )
    event_type = models.CharField(max_length=20, choices=EVENT_TYPES, default="updated")
    summary = models.CharField(max_length=500)
    changes = models.JSONField(default=dict, blank=True)
    project = models.ForeignKey(
        Project, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="inventory_history"
    )
    changed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="makervault_inventory_changes"
    )

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.inventory_item.inventory_id} — {self.summary}"


class BOMItem(TimeStampedModel):
    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name="bom_items")
    board = models.ForeignKey(BoardModel, on_delete=models.SET_NULL, null=True, blank=True, related_name="bom_items")
    component = models.ForeignKey(ComponentModel, on_delete=models.SET_NULL, null=True, blank=True, related_name="bom_items")
    custom_name = models.CharField(max_length=255, blank=True)
    quantity = models.DecimalField(max_digits=12, decimal_places=3, default=1)
    unit = models.CharField(max_length=40, default="item")
    unit_cost = models.DecimalField(max_digits=12, decimal_places=4, blank=True, null=True)
    currency = models.CharField(max_length=3, default="GBP")
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ["created_at"]
        constraints = [
            models.CheckConstraint(condition=models.Q(quantity__gt=0), name="bom_item_quantity_positive"),
        ]

    def clean(self):
        if self.board_id and self.component_id:
            raise ValidationError("A BOM item can reference a board or component, not both.")
        if not self.board_id and not self.component_id and not self.custom_name.strip():
            raise ValidationError({"custom_name": "Enter a name for a custom BOM item."})
        if not self.unit.strip():
            raise ValidationError({"unit": "Unit cannot be blank."})

    @property
    def display_name(self):
        return self.custom_name or str(self.component or self.board or "BOM item")

    def __str__(self):
        return self.display_name


class BOMAllocation(TimeStampedModel):
    bom_item = models.ForeignKey(BOMItem, on_delete=models.CASCADE, related_name="allocations")
    inventory_item = models.ForeignKey(
        InventoryItem, on_delete=models.PROTECT, related_name="bom_allocations"
    )
    quantity = models.DecimalField(max_digits=12, decimal_places=3)
    notes = models.TextField(blank=True)
    allocated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="makervault_bom_allocations"
    )

    class Meta:
        ordering = ["created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["bom_item", "inventory_item"],
                name="unique_bom_inventory_allocation",
            ),
            models.CheckConstraint(
                condition=models.Q(quantity__gt=0),
                name="bom_allocation_quantity_positive",
            ),
        ]

    def clean(self):
        if self.quantity is not None and self.quantity <= 0:
            raise ValidationError({"quantity": "Allocation quantity must be greater than zero."})
        if self.bom_item_id and self.inventory_item_id:
            if self.bom_item.board_id and self.inventory_item.board_id != self.bom_item.board_id:
                raise ValidationError({"inventory_item": "This inventory item does not match the BOM board."})
            if self.bom_item.component_id and self.inventory_item.component_id != self.bom_item.component_id:
                raise ValidationError({"inventory_item": "This inventory item does not match the BOM component."})
            if self.inventory_item.project_id and self.inventory_item.project_id != self.bom_item.project_id:
                raise ValidationError({"inventory_item": "This inventory item is assigned to a different project."})
            if self.inventory_item.status in {"repair", "retired"}:
                raise ValidationError({"inventory_item": "Repair or retired inventory cannot be allocated."})

    def __str__(self):
        return f"{self.bom_item} ← {self.inventory_item} ({self.quantity})"


class FileAsset(TimeStampedModel):
    CATEGORIES = [("image", "Image"), ("wiring", "Wiring / schematic"), ("firmware", "Firmware"), ("source", "Source code"), ("binary", "Executable / binary"), ("document", "Document"), ("cad", "CAD"), ("mesh", "STL / mesh"), ("slicer", "3MF / slicer project"), ("pcb", "PCB"), ("archive", "Archive"), ("other", "Other")]
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=255)
    category = models.CharField(max_length=20, choices=CATEGORIES, default="other")
    file = models.FileField(upload_to="files/%Y/%m/", validators=[validate_maker_file])
    project = models.ForeignKey(Project, on_delete=models.CASCADE, null=True, blank=True, related_name="files")
    board = models.ForeignKey(BoardModel, on_delete=models.SET_NULL, null=True, blank=True, related_name="files")
    component = models.ForeignKey(ComponentModel, on_delete=models.SET_NULL, null=True, blank=True, related_name="files")
    version = models.CharField(max_length=80, blank=True)
    sha256 = models.CharField(max_length=64, blank=True, db_index=True)
    description = models.TextField(blank=True)
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return self.name


class RepositoryLink(TimeStampedModel):
    PROVIDERS = [("github", "GitHub"), ("gitlab", "GitLab"), ("local", "Local"), ("other", "Other")]
    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name="repositories")
    provider = models.CharField(max_length=20, choices=PROVIDERS, default="other")
    name = models.CharField(max_length=255)
    url = models.URLField(blank=True)
    local_path = models.CharField(max_length=500, blank=True)
    default_branch = models.CharField(max_length=120, blank=True)
    metadata = models.JSONField(default=dict, blank=True)

    def __str__(self):
        return self.name


class FilamentManufacturer(TimeStampedModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=200, unique=True)
    website = models.URLField(blank=True)
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class PrinterManufacturer(TimeStampedModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=200, unique=True)
    website = models.URLField(blank=True)
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class PrintingLocation(TimeStampedModel):
    KINDS = [
        ("room", "Room / area"),
        ("shelf", "Shelf"),
        ("drybox", "Dry box"),
        ("storage", "Storage"),
        ("workshop", "Workshop"),
        ("other", "Other"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=200, unique=True)
    kind = models.CharField(max_length=20, choices=KINDS, default="storage")
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class PrintingIntegrationSetting(TimeStampedModel):
    PROVIDERS = [
        ("spoolman", "Spoolman"),
        ("simplyprint", "SimplyPrint"),
        ("creality_cfs", "Creality CFS"),
        ("bambu_ams", "Bambu Lab AMS"),
        ("elegoo", "Elegoo multi-material"),
        ("qidi", "QIDI multi-material"),
        ("snapmaker", "Snapmaker multi-material"),
    ]
    SYNC_DIRECTIONS = [
        ("import", "External → MakerVault"),
        ("export", "MakerVault → external"),
        ("bidirectional", "Bidirectional"),
    ]
    STATUSES = [
        ("disabled", "Disabled"),
        ("not_configured", "Not configured"),
        ("ready", "Ready"),
        ("connected", "Connected"),
        ("disconnected", "Disconnected"),
        ("error", "Error"),
        ("planned", "Planned"),
    ]

    provider = models.CharField(max_length=30, choices=PROVIDERS, unique=True)
    enabled = models.BooleanField(default=False)
    endpoint_url = models.CharField(max_length=500, blank=True)
    sync_direction = models.CharField(max_length=20, choices=SYNC_DIRECTIONS, default="import")
    status = models.CharField(max_length=24, choices=STATUSES, default="not_configured")
    last_checked_at = models.DateTimeField(blank=True, null=True)
    auto_sync = models.BooleanField(default=False)
    sync_interval_minutes = models.PositiveIntegerField(default=15)
    last_sync_at = models.DateTimeField(blank=True, null=True)
    next_sync_at = models.DateTimeField(blank=True, null=True)
    last_sync_triggered_by = models.CharField(max_length=120, blank=True)
    last_sync_result = models.JSONField(default=dict, blank=True)
    last_error = models.TextField(blank=True)
    config = models.JSONField(default=dict, blank=True)

    def clean(self):
        super().clean()
        if self.sync_interval_minutes < 1 or self.sync_interval_minutes > 1440:
            raise ValidationError({"sync_interval_minutes": "Sync interval must be between 1 and 1440 minutes."})

    class Meta:
        ordering = ["provider"]

    def __str__(self):
        return self.get_provider_display()


class PrinterCatalogModel(TimeStampedModel):
    MULTI_MATERIAL_SYSTEMS = [
        ("", "None / unknown"),
        ("creality_cfs", "Creality CFS"),
        ("bambu_ams", "Bambu Lab AMS"),
        ("elegoo", "Elegoo multi-material"),
        ("qidi", "QIDI multi-material"),
        ("snapmaker", "Snapmaker multi-material"),
        ("other", "Other"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    manufacturer = models.ForeignKey(
        PrinterManufacturer, on_delete=models.CASCADE, related_name="models"
    )
    name = models.CharField(max_length=255)
    build_volume_x_mm = models.DecimalField(max_digits=8, decimal_places=2, blank=True, null=True)
    build_volume_y_mm = models.DecimalField(max_digits=8, decimal_places=2, blank=True, null=True)
    build_volume_z_mm = models.DecimalField(max_digits=8, decimal_places=2, blank=True, null=True)
    nozzle_mm = models.DecimalField(max_digits=5, decimal_places=2, default=0.4)
    filament_diameter_mm = models.DecimalField(max_digits=5, decimal_places=2, default=1.75)
    max_nozzle_temp_c = models.SmallIntegerField(blank=True, null=True)
    max_bed_temp_c = models.SmallIntegerField(blank=True, null=True)
    enclosed = models.BooleanField(default=False)
    multi_material_system = models.CharField(
        max_length=30, choices=MULTI_MATERIAL_SYSTEMS, blank=True
    )
    max_multi_material_units = models.PositiveSmallIntegerField(blank=True, null=True)
    features = models.JSONField(default=dict, blank=True)
    image = models.ImageField(upload_to="printers/catalog/", blank=True, null=True)
    image_metadata = models.JSONField(default=dict, blank=True)
    image_multi_material = models.ImageField(
        upload_to="printers/catalog/multi-material/", blank=True, null=True
    )
    image_multi_material_metadata = models.JSONField(default=dict, blank=True)
    source_url = models.URLField(blank=True)

    class Meta:
        ordering = ["manufacturer__name", "name"]
        constraints = [
            models.UniqueConstraint(
                fields=["manufacturer", "name"],
                name="unique_printer_catalogue_model",
            ),
        ]

    def __str__(self):
        return f"{self.manufacturer} {self.name}"


class FilamentProduct(TimeStampedModel):
    TRANSPARENCY = [
        ("opaque", "Opaque"),
        ("translucent", "Translucent"),
        ("transparent", "Transparent"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    manufacturer = models.ForeignKey(Manufacturer, on_delete=models.SET_NULL, null=True, blank=True, related_name="filaments")
    filament_manufacturer = models.ForeignKey(
        FilamentManufacturer, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="filaments"
    )
    source = models.ForeignKey(CatalogSource, on_delete=models.SET_NULL, null=True, blank=True, related_name="filaments")
    name = models.CharField(max_length=255)
    material = models.CharField(max_length=80)
    color_name = models.CharField(max_length=120, blank=True)
    color_hex = models.CharField(max_length=9, blank=True)
    color_hexes = models.JSONField(default=list, blank=True)
    transparency = models.CharField(max_length=16, choices=TRANSPARENCY, default="opaque")
    multi_color_direction = models.CharField(max_length=24, blank=True)
    finish = models.CharField(max_length=40, blank=True)
    pattern = models.CharField(max_length=40, blank=True)
    glow = models.BooleanField(default=False)
    diameter_mm = models.DecimalField(max_digits=5, decimal_places=2, default=1.75)
    density_g_cm3 = models.DecimalField(max_digits=6, decimal_places=3, blank=True, null=True)
    nominal_weight_g = models.DecimalField(max_digits=10, decimal_places=2, blank=True, null=True)
    empty_spool_weight_g = models.DecimalField(max_digits=10, decimal_places=2, blank=True, null=True)
    nozzle_temp_min_c = models.SmallIntegerField(blank=True, null=True)
    nozzle_temp_max_c = models.SmallIntegerField(blank=True, null=True)
    bed_temp_min_c = models.SmallIntegerField(blank=True, null=True)
    bed_temp_max_c = models.SmallIntegerField(blank=True, null=True)
    drying_temp_c = models.SmallIntegerField(blank=True, null=True)
    drying_time_hours = models.DecimalField(max_digits=5, decimal_places=2, blank=True, null=True)
    image = models.ImageField(upload_to="filament/catalog/", blank=True, null=True)
    profile_data = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["filament_manufacturer__name", "name", "color_name"]

    def __str__(self):
        maker = self.filament_manufacturer or self.manufacturer
        return " ".join(filter(None, [str(maker) if maker else "", self.name, self.color_name])).strip()


class Spool(TimeStampedModel):
    STATUS = [("sealed", "Sealed"), ("open", "Open"), ("drying", "Drying"), ("empty", "Empty"), ("retired", "Retired")]
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    spool_id = models.CharField(max_length=40, unique=True)
    rfid_uid = models.CharField(max_length=255, blank=True, default="", db_index=True)
    filament = models.ForeignKey(FilamentProduct, on_delete=models.PROTECT, related_name="spools")
    initial_weight_g = models.DecimalField(max_digits=10, decimal_places=2, blank=True, null=True)
    remaining_weight_g = models.DecimalField(max_digits=10, decimal_places=2, blank=True, null=True)
    purchase_cost = models.DecimalField(max_digits=12, decimal_places=2, blank=True, null=True)
    currency = models.CharField(max_length=3, default="GBP")
    location = models.CharField(max_length=255, blank=True)
    storage_location = models.ForeignKey(
        PrintingLocation, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="spools"
    )
    assigned_printer = models.ForeignKey(
        "Printer", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="assigned_spools"
    )
    status = models.CharField(max_length=20, choices=STATUS, default="sealed")
    opened_on = models.DateField(blank=True, null=True)
    last_dried_at = models.DateTimeField(blank=True, null=True)
    external_spool_id = models.CharField(max_length=255, blank=True)
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ["spool_id"]
        constraints = [
            models.UniqueConstraint(
                fields=["rfid_uid"],
                condition=~models.Q(rfid_uid=""),
                name="unique_nonblank_spool_rfid_uid",
            ),
        ]

    def clean(self):
        super().clean()
        self.rfid_uid = str(self.rfid_uid or "").strip().upper()
        if self.storage_location_id and self.assigned_printer_id:
            raise ValidationError("A spool can be stored at a location or assigned to a printer, not both.")

    def save(self, *args, **kwargs):
        self.rfid_uid = str(self.rfid_uid or "").strip().upper()
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.spool_id} — {self.filament}"


class ExternalSpoolLink(TimeStampedModel):
    PROVIDERS = [
        ("spoolman", "Spoolman"),
        ("simplyprint", "SimplyPrint"),
        ("other", "Other"),
    ]
    SYNC_DIRECTIONS = [
        ("import", "External → MakerVault"),
        ("export", "MakerVault → external"),
        ("bidirectional", "Bidirectional"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    spool = models.ForeignKey(Spool, on_delete=models.CASCADE, related_name="external_links")
    provider = models.CharField(max_length=30, choices=PROVIDERS)
    external_id = models.CharField(max_length=255)
    external_url = models.URLField(blank=True)
    sync_direction = models.CharField(max_length=20, choices=SYNC_DIRECTIONS, default="import")
    last_synced_at = models.DateTimeField(blank=True, null=True)
    sync_metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["provider", "external_id"]
        constraints = [
            models.UniqueConstraint(fields=["provider", "external_id"], name="unique_external_spool_provider_id"),
            models.UniqueConstraint(fields=["spool", "provider"], name="unique_spool_provider_link"),
        ]

    def __str__(self):
        return f"{self.get_provider_display()} {self.external_id} → {self.spool.spool_id}"


class Printer(TimeStampedModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=255)
    manufacturer = models.ForeignKey(Manufacturer, on_delete=models.SET_NULL, null=True, blank=True, related_name="printers")
    printer_manufacturer = models.ForeignKey(
        PrinterManufacturer, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="printers"
    )
    catalog_model = models.ForeignKey(
        PrinterCatalogModel, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="owned_printers"
    )
    model = models.CharField(max_length=255)
    serial_number = models.CharField(max_length=255, blank=True)
    location = models.CharField(max_length=255, blank=True)
    printing_location = models.ForeignKey(
        PrintingLocation, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="printers"
    )
    is_active = models.BooleanField(default=True)
    multi_material_installed = models.BooleanField(default=False)
    connection_host = models.CharField(max_length=255, blank=True)
    build_volume_x_mm = models.DecimalField(max_digits=8, decimal_places=2, blank=True, null=True)
    build_volume_y_mm = models.DecimalField(max_digits=8, decimal_places=2, blank=True, null=True)
    build_volume_z_mm = models.DecimalField(max_digits=8, decimal_places=2, blank=True, null=True)
    nozzle_mm = models.DecimalField(max_digits=5, decimal_places=2, default=0.4)
    profile_data = models.JSONField(default=dict, blank=True)
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class PrinterFilamentSlot(TimeStampedModel):
    SYSTEMS = [
        ("creality_cfs", "Creality CFS"),
        ("bambu_ams", "Bambu Lab AMS"),
        ("elegoo", "Elegoo multi-material"),
        ("qidi", "QIDI multi-material"),
        ("snapmaker", "Snapmaker multi-material"),
        ("generic", "Generic / other"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    printer = models.ForeignKey(Printer, on_delete=models.CASCADE, related_name="filament_slots")
    system = models.CharField(max_length=30, choices=SYSTEMS, default="generic")
    unit_index = models.PositiveSmallIntegerField(default=0)
    slot_index = models.PositiveSmallIntegerField(default=0)
    spool = models.ForeignKey(Spool, on_delete=models.SET_NULL, null=True, blank=True, related_name="printer_slots")
    external_ref = models.CharField(max_length=255, blank=True)
    rfid_uid = models.CharField(max_length=255, blank=True, db_index=True)
    material = models.CharField(max_length=80, blank=True)
    color_name = models.CharField(max_length=120, blank=True)
    color_hex = models.CharField(max_length=9, blank=True)
    remaining_weight_g = models.DecimalField(max_digits=10, decimal_places=2, blank=True, null=True)
    is_loaded = models.BooleanField(default=True)
    last_seen_at = models.DateTimeField(blank=True, null=True)
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["printer__name", "system", "unit_index", "slot_index"]
        constraints = [
            models.UniqueConstraint(
                fields=["printer", "system", "unit_index", "slot_index"],
                name="unique_printer_filament_slot",
            ),
        ]

    def __str__(self):
        return f"{self.printer} · {self.get_system_display()} {self.unit_index}:{self.slot_index}"


class Model3D(TimeStampedModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    project = models.ForeignKey(Project, on_delete=models.CASCADE, null=True, blank=True, related_name="models_3d")
    name = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    source_url = models.URLField(blank=True)
    license = models.CharField(max_length=120, blank=True)
    tags = models.JSONField(default=list, blank=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class ModelRevision(TimeStampedModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    model = models.ForeignKey(Model3D, on_delete=models.CASCADE, related_name="revisions")
    version = models.CharField(max_length=80)
    notes = models.TextField(blank=True)
    source_url = models.URLField(blank=True)
    geometry_metadata = models.JSONField(default=dict, blank=True)
    slicer_metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["model", "version"], name="unique_model_revision")]
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.model} {self.version}"


class ModelRevisionAsset(TimeStampedModel):
    ROLES = [
        ("model", "Printable model"),
        ("slicer", "Slicer project"),
        ("cad", "CAD / source"),
        ("reference", "Reference"),
        ("other", "Other"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    revision = models.ForeignKey(ModelRevision, on_delete=models.CASCADE, related_name="assets")
    file_asset = models.ForeignKey(FileAsset, on_delete=models.PROTECT, related_name="model_revisions")
    role = models.CharField(max_length=20, choices=ROLES, default="model")
    is_primary = models.BooleanField(default=False)
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ["role", "-is_primary", "created_at"]
        constraints = [
            models.UniqueConstraint(fields=["revision", "file_asset"], name="unique_revision_file_asset"),
        ]

    def clean(self):
        if self.file_asset_id and self.role == "model" and self.file_asset.category not in {"mesh", "slicer", "cad"}:
            raise ValidationError({"file_asset": "Printable model assets should use a mesh, slicer or CAD file category."})

    def __str__(self):
        return f"{self.revision} · {self.file_asset.name}"


class ProductListing(TimeStampedModel):
    MARKETPLACES = [("amazon", "Amazon"), ("aliexpress", "AliExpress"), ("ebay", "eBay"), ("manufacturer", "Manufacturer"), ("other", "Other")]
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    marketplace = models.CharField(max_length=30, choices=MARKETPLACES, default="other")
    title = models.CharField(max_length=500)
    url = models.URLField(max_length=1000)
    board = models.ForeignKey(BoardModel, on_delete=models.CASCADE, null=True, blank=True, related_name="listings")
    component = models.ForeignKey(ComponentModel, on_delete=models.CASCADE, null=True, blank=True, related_name="listings")
    filament = models.ForeignKey(FilamentProduct, on_delete=models.CASCADE, null=True, blank=True, related_name="listings")
    seller = models.CharField(max_length=255, blank=True)
    price = models.DecimalField(max_digits=12, decimal_places=2, blank=True, null=True)
    currency = models.CharField(max_length=3, default="GBP")
    pack_quantity = models.DecimalField(max_digits=12, decimal_places=3, default=1)
    image_url = models.URLField(max_length=1000, blank=True)
    external_id = models.CharField(max_length=255, blank=True)
    source_data = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["-updated_at"]

    def __str__(self):
        return self.title


class PrintJob(TimeStampedModel):
    STATUS = [("planned", "Planned"), ("printing", "Printing"), ("success", "Success"), ("failed", "Failed"), ("cancelled", "Cancelled")]
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    model_revision = models.ForeignKey(ModelRevision, on_delete=models.SET_NULL, null=True, blank=True, related_name="prints")
    project = models.ForeignKey(Project, on_delete=models.SET_NULL, null=True, blank=True, related_name="print_jobs")
    printer = models.ForeignKey(Printer, on_delete=models.PROTECT, related_name="print_jobs")
    status = models.CharField(max_length=20, choices=STATUS, default="planned")
    quantity = models.PositiveIntegerField(default=1)
    currency = models.CharField(max_length=3, default="GBP")
    estimated_minutes = models.PositiveIntegerField(blank=True, null=True)
    actual_minutes = models.PositiveIntegerField(blank=True, null=True)
    layer_height_mm = models.DecimalField(max_digits=5, decimal_places=3, blank=True, null=True)
    nozzle_mm = models.DecimalField(max_digits=5, decimal_places=2, blank=True, null=True)
    slicer = models.CharField(max_length=120, blank=True)
    settings = models.JSONField(default=dict, blank=True)
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"Print {self.id} ({self.get_status_display()})"


class PrintMaterialUsage(TimeStampedModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    print_job = models.ForeignKey(PrintJob, on_delete=models.CASCADE, related_name="material_usages")
    spool = models.ForeignKey(Spool, on_delete=models.SET_NULL, null=True, blank=True, related_name="print_material_usages")
    filament = models.ForeignKey(FilamentProduct, on_delete=models.SET_NULL, null=True, blank=True, related_name="print_material_usages")
    printer_slot = models.ForeignKey(
        PrinterFilamentSlot,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="print_material_usages",
    )
    used_g = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    waste_g = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    material_cost = models.DecimalField(max_digits=12, decimal_places=2, blank=True, null=True)
    currency = models.CharField(max_length=3, default="GBP")
    notes = models.TextField(blank=True)
    source_metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["created_at"]
        constraints = [
            models.CheckConstraint(condition=models.Q(used_g__gte=0), name="print_material_used_nonnegative"),
            models.CheckConstraint(condition=models.Q(waste_g__gte=0), name="print_material_waste_nonnegative"),
        ]

    def clean(self):
        if self.spool_id and self.filament_id and self.spool.filament_id != self.filament_id:
            raise ValidationError({"filament": "Selected filament does not match the selected spool."})
        if self.spool_id and not self.filament_id:
            self.filament = self.spool.filament

    def __str__(self):
        material = self.spool.spool_id if self.spool else str(self.filament or "Material")
        return f"{self.print_job} · {material}"
