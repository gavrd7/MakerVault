from django.db import migrations
from django.db.models import Count


def merge_duplicate_components(apps, schema_editor):
    ComponentModel = apps.get_model("core", "ComponentModel")
    InventoryItem = apps.get_model("core", "InventoryItem")
    BOMItem = apps.get_model("core", "BOMItem")
    FileAsset = apps.get_model("core", "FileAsset")
    ProductListing = apps.get_model("core", "ProductListing")

    duplicate_keys = (
        ComponentModel.objects.values("name", "part_number")
        .annotate(total=Count("id"))
        .filter(total__gt=1)
    )

    for key in duplicate_keys.iterator():
        components = list(
            ComponentModel.objects.filter(
                name=key["name"],
                part_number=key["part_number"],
            ).order_by("created_at", "pk")
        )
        canonical = components[0]

        for duplicate in components[1:]:
            changed_fields = []

            if canonical.category_id is None and duplicate.category_id is not None:
                canonical.category_id = duplicate.category_id
                changed_fields.append("category")

            if canonical.source_id is None and duplicate.source_id is not None:
                canonical.source_id = duplicate.source_id
                changed_fields.append("source")

            if not canonical.description and duplicate.description:
                canonical.description = duplicate.description
                changed_fields.append("description")

            if not canonical.image and duplicate.image:
                canonical.image = duplicate.image
                changed_fields.append("image")

            merged_specs = dict(duplicate.specifications or {})
            merged_specs.update(canonical.specifications or {})
            if merged_specs != (canonical.specifications or {}):
                canonical.specifications = merged_specs
                changed_fields.append("specifications")

            if changed_fields:
                canonical.save(update_fields=[*changed_fields, "updated_at"])

            InventoryItem.objects.filter(component_id=duplicate.pk).update(
                component_id=canonical.pk
            )
            BOMItem.objects.filter(component_id=duplicate.pk).update(
                component_id=canonical.pk
            )
            FileAsset.objects.filter(component_id=duplicate.pk).update(
                component_id=canonical.pk
            )
            ProductListing.objects.filter(component_id=duplicate.pk).update(
                component_id=canonical.pk
            )

            duplicate.delete()


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0021_drop_component_manufacturer_field"),
    ]

    operations = [
        migrations.RunPython(
            merge_duplicate_components,
            migrations.RunPython.noop,
        ),
    ]
