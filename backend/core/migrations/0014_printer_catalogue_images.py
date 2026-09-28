from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0013_spool_rfid_uid"),
    ]

    operations = [
        migrations.AddField(
            model_name="printercatalogmodel",
            name="image",
            field=models.ImageField(blank=True, null=True, upload_to="printers/catalog/"),
        ),
        migrations.AddField(
            model_name="printercatalogmodel",
            name="image_metadata",
            field=models.JSONField(blank=True, default=dict),
        ),
    ]
