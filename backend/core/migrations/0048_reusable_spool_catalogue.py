import uuid
from django.db import migrations, models
import django.db.models.deletion


def seed_reusable_catalogue(apps, schema_editor):
    Entry = apps.get_model("core", "ReusableSpoolCatalogEntry")
    seed = [
        ("bambu-basic", "Bambu Lab", "Bambu Reusable Spool (Basic)", "manufacturer",
         "https://asia.store.bambulab.com/collections/filament-accessories/products/bambu-reusable-spool",
         "ABS", "250.00", 70),
        ("bambu-high-temp", "Bambu Lab", "Bambu Reusable Spool (High Temperature)", "manufacturer",
         "https://eu.store.bambulab.com/en-at/products/high-temperature-reusable-spool",
         "ABS+PC", "250.00", 90),
        ("prusa-refill-1kg", "Prusa Research", "Prusament Refill 1kg Reusable Spool (Legacy)", "manufacturer",
         "https://help.prusa3d.com/article/how-to-use-prusament-refill-1kg_394630", "", None, None),
        ("prusa-refill-900g", "Prusa Research", "Prusament Refill 900g Reusable Spool (New)", "manufacturer",
         "https://help.prusa3d.com/guide/how-to-use-prusament-refill-900g_440297", "", None, None),
        ("polymaker-master-printable", "Polymaker", "Panchroma Master Reusable Spool (Printable)", "printed",
         "https://wiki.polymaker.com/polymaker-products/polymaker-filaments/panchroma-tm/panchroma-tm-pla-refill",
         "", None, None),
    ]
    for key, maker, name, kind, source, material, tare, temperature in seed:
        Entry.objects.get_or_create(
            key=key,
            defaults=dict(
                manufacturer=maker, name=name, design_type=kind, source_url=source,
                material=material, nominal_tare_g=tare, max_dryer_temp_c=temperature,
                temperature_source=source if temperature is not None else "",
                verified=True,
                provenance={"source": source, "type": "manufacturer_reference", "seed_version": 1},
            ),
        )


def link_existing_designs(apps, schema_editor):
    Entry = apps.get_model("core", "ReusableSpoolCatalogEntry")
    Design = apps.get_model("core", "ReusableSpoolDesign")
    for entry in Entry.objects.all():
        Design.objects.filter(
            catalog_entry__isnull=True, name=entry.name, manufacturer=entry.manufacturer
        ).update(catalog_entry=entry)


class Migration(migrations.Migration):
    dependencies = [("core", "0047_reusable_spool_hex_color")]

    operations = [
        migrations.CreateModel(
            name="ReusableSpoolCatalogEntry",
            fields=[
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("id", models.UUIDField(primary_key=True, serialize=False, default=uuid.uuid4, editable=False)),
                ("key", models.SlugField(max_length=120, unique=True)),
                ("manufacturer", models.CharField(max_length=120)),
                ("name", models.CharField(max_length=200)),
                ("design_type", models.CharField(max_length=20, choices=[("manufacturer", "Manufacturer-made"), ("printed", "3D printed")])),
                ("material", models.CharField(max_length=80, blank=True)),
                ("description", models.TextField(blank=True)),
                ("source_url", models.URLField(blank=True)),
                ("image_url", models.URLField(blank=True)),
                ("nominal_tare_g", models.DecimalField(max_digits=8, decimal_places=2, blank=True, null=True)),
                ("max_dryer_temp_c", models.PositiveSmallIntegerField(blank=True, null=True)),
                ("temperature_source", models.URLField(blank=True)),
                ("outer_diameter_mm", models.DecimalField(max_digits=7, decimal_places=2, blank=True, null=True)),
                ("width_mm", models.DecimalField(max_digits=7, decimal_places=2, blank=True, null=True)),
                ("hub_diameter_mm", models.DecimalField(max_digits=7, decimal_places=2, blank=True, null=True)),
                ("capacity_g", models.DecimalField(max_digits=8, decimal_places=2, blank=True, null=True)),
                ("verified", models.BooleanField(default=False)),
                ("provenance", models.JSONField(blank=True, default=dict)),
            ],
            options={"ordering": ["manufacturer", "name"]},
        ),
        migrations.AddField(
            model_name="reusablespooldesign",
            name="catalog_entry",
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL,
                                    related_name="personal_designs", to="core.reusablespoolcatalogentry"),
        ),
        migrations.RunPython(seed_reusable_catalogue, migrations.RunPython.noop),
        migrations.RunPython(link_existing_designs, migrations.RunPython.noop),
    ]
