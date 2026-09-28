from django.db import migrations, models


def preserve_existing_discovered_multi_material_systems(apps, schema_editor):
    Printer = apps.get_model("core", "Printer")
    PrinterFilamentSlot = apps.get_model("core", "PrinterFilamentSlot")

    printer_ids = (
        PrinterFilamentSlot.objects.exclude(system="generic")
        .values_list("printer_id", flat=True)
        .distinct()
    )
    Printer.objects.filter(pk__in=printer_ids).update(multi_material_installed=True)


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0014_printer_catalogue_images"),
    ]

    operations = [
        migrations.AddField(
            model_name="printer",
            name="multi_material_installed",
            field=models.BooleanField(default=False),
        ),
        migrations.RunPython(
            preserve_existing_discovered_multi_material_systems,
            migrations.RunPython.noop,
        ),
    ]
