from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0015_printer_multi_material_installed"),
    ]

    operations = [
        migrations.AddField(
            model_name="printercatalogmodel",
            name="image_multi_material",
            field=models.ImageField(
                blank=True,
                null=True,
                upload_to="printers/catalog/multi-material/",
            ),
        ),
        migrations.AddField(
            model_name="printercatalogmodel",
            name="image_multi_material_metadata",
            field=models.JSONField(blank=True, default=dict),
        ),
    ]
