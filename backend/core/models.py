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
    inventory_item = models.ForeignKey(InventoryItem, on_delete=models.SET_NULL, null=True, blank=True, related_name="bom_items")
    custom_name = models.CharField(max_length=255, blank=True)
    quantity = models.DecimalField(max_digits=12, decimal_places=3, default=1)
    unit = models.CharField(max_length=40, default="item")
    unit_cost = models.DecimalField(max_digits=12, decimal_places=4, blank=True, null=True)
    currency = models.CharField(max_length=3, default="GBP")
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ["created_at"]

    def __str__(self):
        return self.custom_name or str(self.component or self.board or self.inventory_item or "BOM item")


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


class FilamentProduct(TimeStampedModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    manufacturer = models.ForeignKey(Manufacturer, on_delete=models.SET_NULL, null=True, blank=True, related_name="filaments")
    source = models.ForeignKey(CatalogSource, on_delete=models.SET_NULL, null=True, blank=True, related_name="filaments")
    name = models.CharField(max_length=255)
    material = models.CharField(max_length=80)
    color_name = models.CharField(max_length=120, blank=True)
    color_hex = models.CharField(max_length=9, blank=True)
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
        ordering = ["manufacturer__name", "name", "color_name"]

    def __str__(self):
        return " ".join(filter(None, [str(self.manufacturer) if self.manufacturer else "", self.name, self.color_name])).strip()


class Spool(TimeStampedModel):
    STATUS = [("sealed", "Sealed"), ("open", "Open"), ("drying", "Drying"), ("empty", "Empty"), ("retired", "Retired")]
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    spool_id = models.CharField(max_length=40, unique=True)
    filament = models.ForeignKey(FilamentProduct, on_delete=models.PROTECT, related_name="spools")
    initial_weight_g = models.DecimalField(max_digits=10, decimal_places=2, blank=True, null=True)
    remaining_weight_g = models.DecimalField(max_digits=10, decimal_places=2, blank=True, null=True)
    purchase_cost = models.DecimalField(max_digits=12, decimal_places=2, blank=True, null=True)
    currency = models.CharField(max_length=3, default="GBP")
    location = models.CharField(max_length=255, blank=True)
    status = models.CharField(max_length=20, choices=STATUS, default="sealed")
    opened_on = models.DateField(blank=True, null=True)
    last_dried_at = models.DateTimeField(blank=True, null=True)
    external_spool_id = models.CharField(max_length=255, blank=True)
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ["spool_id"]

    def __str__(self):
        return f"{self.spool_id} — {self.filament}"


class Printer(TimeStampedModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=255)
    manufacturer = models.ForeignKey(Manufacturer, on_delete=models.SET_NULL, null=True, blank=True, related_name="printers")
    model = models.CharField(max_length=255)
    serial_number = models.CharField(max_length=255, blank=True)
    location = models.CharField(max_length=255, blank=True)
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
    stl_file = models.FileField(upload_to="models/stl/", validators=[validate_maker_file], blank=True, null=True)
    three_mf_file = models.FileField(upload_to="models/3mf/", validators=[validate_maker_file], blank=True, null=True)
    cad_file = models.FileField(upload_to="models/cad/", validators=[validate_maker_file], blank=True, null=True)
    source_url = models.URLField(blank=True)
    geometry_metadata = models.JSONField(default=dict, blank=True)
    slicer_metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["model", "version"], name="unique_model_revision")]
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.model} {self.version}"


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
    spool = models.ForeignKey(Spool, on_delete=models.SET_NULL, null=True, blank=True, related_name="print_jobs")
    status = models.CharField(max_length=20, choices=STATUS, default="planned")
    quantity = models.PositiveIntegerField(default=1)
    filament_used_g = models.DecimalField(max_digits=10, decimal_places=2, blank=True, null=True)
    waste_g = models.DecimalField(max_digits=10, decimal_places=2, blank=True, null=True)
    material_cost = models.DecimalField(max_digits=12, decimal_places=2, blank=True, null=True)
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
