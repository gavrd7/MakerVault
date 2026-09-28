from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0016_printer_multi_material_image_variant"),
    ]

    operations = [
        migrations.AddField(
            model_name="cataloguemaintenancesettings",
            name="check_printer_data",
            field=models.BooleanField(default=True),
        ),
    ]
