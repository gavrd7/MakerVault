from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0017_catalogue_maintenance_printer_data"),
    ]

    operations = [
        migrations.AlterField(
            model_name="printercatalogmodel",
            name="enclosed",
            field=models.BooleanField(blank=True, default=None, null=True),
        ),
    ]
