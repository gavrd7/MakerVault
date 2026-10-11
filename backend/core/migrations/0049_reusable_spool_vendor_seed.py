from django.db import migrations


def add_verified_reusable_spools(apps, schema_editor):
    Entry = apps.get_model("core", "ReusableSpoolCatalogEntry")
    records = [
        {
            "key": "esun-espool-plus", "manufacturer": "eSUN",
            "name": "eSpool+", "design_type": "manufacturer",
            "material": "ABS", "nominal_tare_g": "210.00",
            "outer_diameter_mm": "200.00", "width_mm": "80.00",
            "description": "Detachable eSpool+ for Refilament; 200 mm diameter, 80 mm width and 210 g weight from official eSUN listing. No verified dryer limit.",
            "source_url": "https://uk.esun3d.com/espool",
            "provenance": {"source": "https://uk.esun3d.com/espool", "verified_fields": ["manufacturer", "name", "design_type", "material", "nominal_tare_g", "outer_diameter_mm", "width_mm"], "seed_version": 2},
        },
        {
            "key": "sunlu-third-generation", "manufacturer": "SUNLU",
            "name": "Third-Generation Reusable Spool",
            "design_type": "manufacturer", "outer_diameter_mm": "200.00",
            "width_mm": "55.00",
            "description": "Detachable SUNLU 3rd-generation spool, 200 mm diameter by 55 mm width; made from an unspecified high-strength material. Tare and dryer rating unknown.",
            "source_url": "https://store.sunlu.com/blogs/products-review/sunlu-third-generation-reusable-spool-a-new-choice-for-eco-friendly-durable-and-efficient-filament-management",
            "provenance": {"source": "https://store.sunlu.com/blogs/products-review/sunlu-third-generation-reusable-spool-a-new-choice-for-eco-friendly-durable-and-efficient-filament-management", "verified_fields": ["manufacturer", "name", "design_type", "outer_diameter_mm", "width_mm"], "seed_version": 2},
        },
    ]
    for values in records:
        key = values.pop("key")
        Entry.objects.get_or_create(key=key, defaults={**values, "verified": True})


class Migration(migrations.Migration):
    dependencies = [("core", "0048_reusable_spool_catalogue")]
    operations = [migrations.RunPython(add_verified_reusable_spools, migrations.RunPython.noop)]
