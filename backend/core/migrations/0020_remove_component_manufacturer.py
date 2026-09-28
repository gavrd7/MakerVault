from django.db import migrations


def remove_component_only_manufacturers(apps, schema_editor):
    Manufacturer = apps.get_model("core", "Manufacturer")
    ComponentModel = apps.get_model("core", "ComponentModel")
    BoardModel = apps.get_model("core", "BoardModel")
    FilamentProduct = apps.get_model("core", "FilamentProduct")
    Printer = apps.get_model("core", "Printer")

    candidate_ids = set(
        ComponentModel.objects.exclude(manufacturer_id=None)
        .values_list("manufacturer_id", flat=True)
    )
    for manufacturer_id in candidate_ids:
        if BoardModel.objects.filter(manufacturer_id=manufacturer_id).exists():
            continue
        if FilamentProduct.objects.filter(manufacturer_id=manufacturer_id).exists():
            continue
        if Printer.objects.filter(manufacturer_id=manufacturer_id).exists():
            continue
        Manufacturer.objects.filter(pk=manufacturer_id).delete()


class Migration(migrations.Migration):
    # PostgreSQL can leave deferred FK trigger events pending after the
    # manufacturer cleanup. The following RemoveField performs ALTER TABLE,
    # which PostgreSQL refuses while those events are still pending.
    #
    # Keep the migration non-atomic so the cleanup transaction commits before
    # the schema change. The cleanup itself remains atomic.
    atomic = False

    dependencies = [
        ("core", "0019_external_printer_links_simplyprint_slots"),
    ]

    operations = [
        migrations.RunPython(
            remove_component_only_manufacturers,
            migrations.RunPython.noop,
            atomic=True,
        ),
        migrations.RemoveField(
            model_name="componentmodel",
            name="manufacturer",
        ),
    ]
