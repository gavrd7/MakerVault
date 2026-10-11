"""Expand reusable spool catalogue with source-backed hardware variants.

No image is copied from retailers, and approximate/unsafe temperature
claims are stored as provenance rather than as dryer safety limits.
"""
from django.db import migrations


def add_reusable_spool_variants(apps, schema_editor):
    Entry = apps.get_model("core", "ReusableSpoolCatalogEntry")
    esun = "https://www.esun3d.com/espool-2-0"
    recycling = "https://www.3djake.uk/recycling-fabrik/multispool-reusable-spool?sai=40266"
    entries = [
        {
            "key": "esun-espool-plus-2",
            "manufacturer": "eSUN",
            "name": "eSpool+ 2.0",
            "design_type": "manufacturer",
            "source_url": esun,
            "description": (
                "Second-generation modular detachable eSUN spool with "
                "improved twist-lock assembly. Distinct from first-generation "
                "eSpool+. Empty tare, material, geometry and dryer rating "
                "are not yet independently verified."
            ),
            "verified": True,
            "provenance": {
                "source": esun,
                "source_type": "manufacturer",
                "revision": "2.0",
                "verified_fields": ["manufacturer", "name", "design_type", "revision"],
                "unverified_fields": [
                    "nominal_tare_g", "material", "outer_diameter_mm", "width_mm",
                    "hub_diameter_mm", "capacity_g", "max_dryer_temp_c",
                ],
                "image_status": "pending_rights_review",
                "seed_version": 5,
            },
        },
    ]
    for slug, material, sku in (
        ("rpla", "rPLA", "MISC-PHYS-XPLA-MUSP"),
        ("rpetg", "rPETG", ""),
    ):
        entries.append({
            "key": "recycling-fabrik-multispool-" + slug,
            "manufacturer": "Recycling Fabrik",
            "name": "MultiSpool (" + material + ")",
            "design_type": "manufacturer",
            "material": material,
            "nominal_tare_g": "150.00",
            "source_url": recycling,
            "description": (
                "Reusable spool made from recycled " + material +
                "; reseller states approximately 150 g empty weight. "
                "Explicitly NOT suitable for a filament dryer; retailer "
                "advises against exposure above 60 C. Printable STL "
                "alternative is offered separately and is not this SKU."
            ),
            "verified": True,
            "provenance": {
                "source": recycling,
                "source_type": "reseller",
                "source_product_sku": sku,
                "approximate_tare_g": True,
                "avoid_dryer": True,
                "reseller_exposure_limit_c": 60,
                "verified_fields": [
                    "manufacturer", "name", "design_type", "material",
                    "nominal_tare_g",
                ],
                "unverified_fields": [
                    "outer_diameter_mm", "width_mm", "hub_diameter_mm",
                    "capacity_g", "max_dryer_temp_c",
                ],
                "image_status": "pending_rights_review",
                "seed_version": 5,
            },
        })
    for values in entries:
        key = values.pop("key")
        Entry.objects.get_or_create(key=key, defaults=values)


class Migration(migrations.Migration):
    dependencies = [("core", "0053_formfutura_reusable_masterspools")]
    operations = [migrations.RunPython(add_reusable_spool_variants, migrations.RunPython.noop)]
