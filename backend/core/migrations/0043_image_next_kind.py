from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("core", "0042_filament_enrichment_cursor")]

    operations = [
        migrations.AddField(
            model_name="cataloguemaintenancesettings",
            name="image_next_kind",
            field=models.CharField(blank=True, default="", max_length=20),
        ),
    ]
