import uuid

from django.db import migrations, models
import django.db.models.deletion


def migrate_printing_domains(apps, schema_editor):
    Manufacturer = apps.get_model("core", "Manufacturer")
    FilamentManufacturer = apps.get_model("core", "FilamentManufacturer")
    PrinterManufacturer = apps.get_model("core", "PrinterManufacturer")
    PrintingLocation = apps.get_model("core", "PrintingLocation")
    FilamentProduct = apps.get_model("core", "FilamentProduct")
    Printer = apps.get_model("core", "Printer")
    Spool = apps.get_model("core", "Spool")

    maker_names = {
        row["id"]: row["name"]
        for row in Manufacturer.objects.values("id", "name")
    }

    for filament in FilamentProduct.objects.exclude(manufacturer_id=None).iterator():
        name = maker_names.get(filament.manufacturer_id)
        if not name:
            continue
        maker, _ = FilamentManufacturer.objects.get_or_create(name=name)
        filament.filament_manufacturer_id = maker.pk
        filament.save(update_fields=["filament_manufacturer"])

    for printer in Printer.objects.exclude(manufacturer_id=None).iterator():
        name = maker_names.get(printer.manufacturer_id)
        if not name:
            continue
        maker, _ = PrinterManufacturer.objects.get_or_create(name=name)
        printer.printer_manufacturer_id = maker.pk
        printer.save(update_fields=["printer_manufacturer"])

    location_cache = {}
    for printer in Printer.objects.exclude(location="").iterator():
        name = printer.location.strip()
        if not name:
            continue
        location = location_cache.get(name)
        if location is None:
            location, _ = PrintingLocation.objects.get_or_create(
                name=name,
                defaults={"kind": "other"},
            )
            location_cache[name] = location
        printer.printing_location_id = location.pk
        printer.save(update_fields=["printing_location"])

    for spool in Spool.objects.exclude(location="").iterator():
        name = spool.location.strip()
        if not name:
            continue
        location = location_cache.get(name)
        if location is None:
            location, _ = PrintingLocation.objects.get_or_create(
                name=name,
                defaults={"kind": "storage"},
            )
            location_cache[name] = location
        spool.storage_location_id = location.pk
        spool.save(update_fields=["storage_location"])


def seed_integration_rows(apps, schema_editor):
    PrintingIntegrationSetting = apps.get_model("core", "PrintingIntegrationSetting")
    defaults = {
        "spoolman": {"status": "not_configured", "sync_direction": "bidirectional"},
        "simplyprint": {"status": "planned", "sync_direction": "import"},
        "creality_cfs": {"status": "ready", "sync_direction": "import"},
        "bambu_ams": {"status": "planned", "sync_direction": "import"},
        "elegoo": {"status": "planned", "sync_direction": "import"},
        "qidi": {"status": "planned", "sync_direction": "import"},
        "snapmaker": {"status": "planned", "sync_direction": "import"},
    }
    for provider, values in defaults.items():
        PrintingIntegrationSetting.objects.get_or_create(provider=provider, defaults=values)


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0010_filament_catalogue_metadata"),
    ]

    operations = [
        migrations.CreateModel(
            name="FilamentManufacturer",
            fields=[
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("name", models.CharField(max_length=200, unique=True)),
                ("website", models.URLField(blank=True)),
                ("metadata", models.JSONField(blank=True, default=dict)),
            ],
            options={"ordering": ["name"]},
        ),
        migrations.CreateModel(
            name="PrinterManufacturer",
            fields=[
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("name", models.CharField(max_length=200, unique=True)),
                ("website", models.URLField(blank=True)),
                ("metadata", models.JSONField(blank=True, default=dict)),
            ],
            options={"ordering": ["name"]},
        ),
        migrations.CreateModel(
            name="PrintingIntegrationSetting",
            fields=[
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("provider", models.CharField(choices=[("spoolman", "Spoolman"), ("simplyprint", "SimplyPrint"), ("creality_cfs", "Creality CFS"), ("bambu_ams", "Bambu Lab AMS"), ("elegoo", "Elegoo multi-material"), ("qidi", "QIDI multi-material"), ("snapmaker", "Snapmaker multi-material")], max_length=30, unique=True)),
                ("enabled", models.BooleanField(default=False)),
                ("endpoint_url", models.CharField(blank=True, max_length=500)),
                ("sync_direction", models.CharField(choices=[("import", "External → MakerVault"), ("export", "MakerVault → external"), ("bidirectional", "Bidirectional")], default="import", max_length=20)),
                ("status", models.CharField(choices=[("disabled", "Disabled"), ("not_configured", "Not configured"), ("ready", "Ready"), ("connected", "Connected"), ("error", "Error"), ("planned", "Planned")], default="not_configured", max_length=24)),
                ("last_checked_at", models.DateTimeField(blank=True, null=True)),
                ("last_error", models.TextField(blank=True)),
                ("config", models.JSONField(blank=True, default=dict)),
            ],
            options={"ordering": ["provider"]},
        ),
        migrations.CreateModel(
            name="PrintingLocation",
            fields=[
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("name", models.CharField(max_length=200, unique=True)),
                ("kind", models.CharField(choices=[("room", "Room / area"), ("shelf", "Shelf"), ("drybox", "Dry box"), ("storage", "Storage"), ("workshop", "Workshop"), ("other", "Other")], default="storage", max_length=20)),
                ("notes", models.TextField(blank=True)),
            ],
            options={"ordering": ["name"]},
        ),
        migrations.CreateModel(
            name="PrinterCatalogModel",
            fields=[
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("name", models.CharField(max_length=255)),
                ("build_volume_x_mm", models.DecimalField(blank=True, decimal_places=2, max_digits=8, null=True)),
                ("build_volume_y_mm", models.DecimalField(blank=True, decimal_places=2, max_digits=8, null=True)),
                ("build_volume_z_mm", models.DecimalField(blank=True, decimal_places=2, max_digits=8, null=True)),
                ("nozzle_mm", models.DecimalField(decimal_places=2, default=0.4, max_digits=5)),
                ("filament_diameter_mm", models.DecimalField(decimal_places=2, default=1.75, max_digits=5)),
                ("max_nozzle_temp_c", models.SmallIntegerField(blank=True, null=True)),
                ("max_bed_temp_c", models.SmallIntegerField(blank=True, null=True)),
                ("enclosed", models.BooleanField(default=False)),
                ("multi_material_system", models.CharField(blank=True, choices=[("", "None / unknown"), ("creality_cfs", "Creality CFS"), ("bambu_ams", "Bambu Lab AMS"), ("elegoo", "Elegoo multi-material"), ("qidi", "QIDI multi-material"), ("snapmaker", "Snapmaker multi-material"), ("other", "Other")], max_length=30)),
                ("max_multi_material_units", models.PositiveSmallIntegerField(blank=True, null=True)),
                ("features", models.JSONField(blank=True, default=dict)),
                ("source_url", models.URLField(blank=True)),
                ("manufacturer", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="models", to="core.printermanufacturer")),
            ],
            options={"ordering": ["manufacturer__name", "name"]},
        ),
        migrations.AddConstraint(
            model_name="printercatalogmodel",
            constraint=models.UniqueConstraint(fields=("manufacturer", "name"), name="unique_printer_catalogue_model"),
        ),
        migrations.AddField(
            model_name="filamentproduct",
            name="filament_manufacturer",
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="filaments", to="core.filamentmanufacturer"),
        ),
        migrations.AddField(
            model_name="printer",
            name="catalog_model",
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="owned_printers", to="core.printercatalogmodel"),
        ),
        migrations.AddField(
            model_name="printer",
            name="connection_host",
            field=models.CharField(blank=True, max_length=255),
        ),
        migrations.AddField(
            model_name="printer",
            name="is_active",
            field=models.BooleanField(default=True),
        ),
        migrations.AddField(
            model_name="printer",
            name="printer_manufacturer",
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="printers", to="core.printermanufacturer"),
        ),
        migrations.AddField(
            model_name="printer",
            name="printing_location",
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="printers", to="core.printinglocation"),
        ),
        migrations.AddField(
            model_name="spool",
            name="assigned_printer",
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="assigned_spools", to="core.printer"),
        ),
        migrations.AddField(
            model_name="spool",
            name="storage_location",
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="spools", to="core.printinglocation"),
        ),
        migrations.AlterModelOptions(
            name="filamentproduct",
            options={"ordering": ["filament_manufacturer__name", "name", "color_name"]},
        ),
        migrations.RunPython(migrate_printing_domains, migrations.RunPython.noop),
        migrations.RunPython(seed_integration_rows, migrations.RunPython.noop),
    ]
