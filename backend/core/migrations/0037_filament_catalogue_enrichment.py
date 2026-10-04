from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0036_experimental_printer_capabilities"),
    ]

    operations = [
        migrations.AddField(
            model_name="cataloguemaintenancesettings",
            name="check_filament_data",
            field=models.BooleanField(default=True),
        ),
        migrations.AddField(
            model_name="filamentproduct",
            name="image_metadata",
            field=models.JSONField(blank=True, default=dict),
        ),
    ]
