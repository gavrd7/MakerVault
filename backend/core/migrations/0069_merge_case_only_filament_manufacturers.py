from django.db import migrations


def merge_case_only_filament_manufacturers(apps, schema_editor):
    """Unify exact case-only aliases without touching filament products or spool IDs."""
    Manufacturer = apps.get_model("core", "FilamentManufacturer")
    Product = apps.get_model("core", "FilamentProduct")
    database = schema_editor.connection.alias
    groups = {}
    for maker in Manufacturer.objects.using(database).order_by("name", "pk").iterator():
        groups.setdefault(maker.name.strip().casefold(), []).append(maker)

    for makers in groups.values():
        if len(makers) < 2:
            continue
        # Prefer the established record referenced by most products. All
        # products retain their identities; only the FK is repointed.
        counts = {
            maker.pk: Product.objects.using(database).filter(filament_manufacturer_id=maker.pk).count()
            for maker in makers
        }
        canonical = sorted(
            makers,
            key=lambda maker: (-counts[maker.pk], maker.name != maker.name.upper(), str(maker.pk)),
        )[0]
        for alias in makers:
            if alias.pk == canonical.pk:
                continue
            if not canonical.website and alias.website:
                canonical.website = alias.website
            if alias.metadata:
                metadata = dict(canonical.metadata or {})
                for key, value in alias.metadata.items():
                    metadata.setdefault(key, value)
                canonical.metadata = metadata
            Product.objects.using(database).filter(
                filament_manufacturer_id=alias.pk
            ).update(filament_manufacturer_id=canonical.pk)
            alias.delete()
        canonical.save(update_fields=["website", "metadata"])


class Migration(migrations.Migration):
    dependencies = [("core", "0068_tag_registration_ndef_handoff")]

    operations = [migrations.RunPython(
        merge_case_only_filament_manufacturers,
        migrations.RunPython.noop,
    )]
