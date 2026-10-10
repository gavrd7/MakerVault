from django.db import migrations


def add_more_reusable_spools(apps, schema_editor):
    Entry = apps.get_model("core", "ReusableSpoolCatalogEntry")
    records = [
        {
            "key": "anycubic-reusable-spool",
            "manufacturer": "Anycubic", "name": "Anycubic Reusable Spool",
            "design_type": "manufacturer", "material": "ABS",
            "outer_diameter_mm": "195.00", "width_mm": "67.00",
            "hub_diameter_mm": "54.50", "max_dryer_temp_c": 100,
            "temperature_source": "https://uk.anycubic.com/products/reusable-spools",
            "source_url": "https://uk.anycubic.com/products/reusable-spools",
            "description": "Official ABS reusable spool with 195 mm diameter, 67 mm width and 54.5 mm arbor hole. Manufacturer rates up to 100°C; tare not specified.",
            "provenance": {"source": "https://uk.anycubic.com/products/reusable-spools",
                           "verified_fields": ["manufacturer", "name", "design_type", "material", "outer_diameter_mm", "width_mm", "hub_diameter_mm", "max_dryer_temp_c"]},
        },
        {
            "key": "elegoo-reusable-spool",
            "manufacturer": "ELEGOO", "name": "ELEGOO Reusable Spool",
            "design_type": "manufacturer",
            "source_url": "https://uk.elegoo.com/collections/elegoo-products-dc/products/reusable-spool",
            "description": "Official reusable spool for ELEGOO refill filaments. No verified tare weight, outer dimensions or temperature limit.",
            "provenance": {"source": "https://uk.elegoo.com/collections/elegoo-products-dc/products/reusable-spool",
                           "verified_fields": ["manufacturer", "name", "design_type"]},
        },
        {
            "key": "spectrum-refill-masterspool",
            "manufacturer": "Spectrum Filaments", "name": "Spectrum ReFill 3D Printed Masterspool",
            "design_type": "printed",
            "source_url": "https://shop.spectrumfilaments.com/product-eng-1945-Spectrum-ReFill-reusable-3D-printed-masterspool.html",
            "description": "Manufacturer-offered 3D printed Spectrum ReFill master spool, SKU 81434 / EAN 5905991405009; advertised compatibility with Bambu AMS.",
            "provenance": {"source": "https://shop.spectrumfilaments.com/product-eng-1945-Spectrum-ReFill-reusable-3D-printed-masterspool.html",
                           "sku": "81434", "ean": "5905991405009",
                           "verified_fields": ["manufacturer", "name", "design_type"]},
        },
        {
            "key": "fiberlogy-reusable-spool",
            "manufacturer": "Fiberlogy", "name": "Fiberlogy Reusable Spool",
            "design_type": "manufacturer",
            "source_url": "https://fiberlogy.com/en/",
            "description": "Fiberlogy's reusable spool system designed to accept refills; confirm specific revision before assigning dimensions or tare weight.",
            "provenance": {"source": "https://fiberlogy.com/en/",
                           "verified_fields": ["manufacturer", "name", "design_type"]},
        },
        {
            "key": "esun-espool-plus-print-model",
            "manufacturer": "eSUN", "name": "eSpool+ Printable Model",
            "design_type": "printed",
            "source_url": "https://www.esun3d.com/wiki/model-download",
            "description": "Manufacturer-published printable eSpool+ model; printed weight, dimensions and dryer rating require the actual print/material.",
            "provenance": {"source": "https://www.esun3d.com/wiki/model-download",
                           "verified_fields": ["manufacturer", "name", "design_type"]},
        },
    ]
    for values in records:
        key = values.pop("key")
        Entry.objects.get_or_create(key=key, defaults={**values, "verified": True})


class Migration(migrations.Migration):
    dependencies = [("core", "0049_reusable_spool_vendor_seed")]
    operations = [migrations.RunPython(add_more_reusable_spools, migrations.RunPython.noop)]
