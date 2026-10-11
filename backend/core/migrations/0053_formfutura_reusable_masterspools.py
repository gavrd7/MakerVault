"""Add manufacturer-documented FormFutura printable master spool variants.

These are two different printable hardware sizes. ReFill coil weights are not
spool tare weights, and are deliberately not recorded as such.
"""
from django.db import migrations


SOURCE = "https://www.formfutura.com/filaments/high-speed-filaments/refill-petg"


def seed_formfutura_masterspools(apps, schema_editor):
    Entry = apps.get_model("core", "ReusableSpoolCatalogEntry")
    for key, name, refill_size in (
        ("formfutura-masterspool-750g", "FormFutura ReFill Printable Master Spool (750g coil)", "750g"),
        ("formfutura-masterspool-2000g", "FormFutura ReFill Printable Master Spool (2000g coil)", "2000g"),
    ):
        Entry.objects.get_or_create(
            key=key,
            defaults={
                "manufacturer": "FormFutura",
                "name": name,
                "design_type": "printed",
                "source_url": SOURCE,
                "description": (
                    "Manufacturer-documented print-your-own reusable master spool "
                    f"for FormFutura ReFill {refill_size} filament coils. The size "
                    "refers to the refill filament, NOT empty spool weight. "
                    "Exact printable file, printed tare, geometry, material and "
                    "safe dryer limit must be verified for the chosen print."
                ),
                "verified": True,
                "provenance": {
                    "source": SOURCE,
                    "type": "manufacturer_reference",
                    "refill_family": "FormFutura ReFill",
                    "compatible_refill_size": refill_size,
                    "verified_fields": ["manufacturer", "name", "design_type", "refill_family", "compatible_refill_size"],
                    "unverified_fields": [
                        "nominal_tare_g", "outer_diameter_mm", "width_mm",
                        "hub_diameter_mm", "capacity_g", "material", "max_dryer_temp_c",
                    ],
                    "image_status": "pending_rights_review",
                    "seed_version": 4,
                },
            },
        )

    # AzureFilm sells this actual reusable hardware separately, including a
    # multi-pack; pack count is not a distinct physical spool design.
    azure_source = "https://azurefilm.com/product/azurefilm-master-spool-10-pack/"
    Entry.objects.get_or_create(
        key="azurefilm-master-spool",
        defaults={
            "manufacturer": "AzureFilm",
            "name": "AzureFilm Master Spool",
            "design_type": "manufacturer",
            "source_url": azure_source,
            "description": (
                "Manufacturer-produced reusable two-disc, injection-moulded "
                "master spool for AzureFilm Refill filament. Also sold in "
                "multi-packs; pack size and 1 kg refill mass are not hardware "
                "variants or empty spool tare. Exact material, dimensions and "
                "dryer limit are not confirmed here."
            ),
            "verified": True,
            "provenance": {
                "source": azure_source,
                "type": "manufacturer_reference",
                "refill_family": "AzureFilm Refill",
                "verified_fields": [
                    "manufacturer", "name", "design_type",
                    "refill_family", "injection_moulded_two_disc_construction",
                ],
                "unverified_fields": [
                    "nominal_tare_g", "outer_diameter_mm", "width_mm",
                    "hub_diameter_mm", "capacity_g", "material", "max_dryer_temp_c",
                ],
                "image_status": "pending_rights_review",
                "seed_version": 4,
            },
        },
    )


class Migration(migrations.Migration):
    dependencies = [("core", "0052_maker_tag_reusable_spool_target")]
    operations = [migrations.RunPython(seed_formfutura_masterspools, migrations.RunPython.noop)]
