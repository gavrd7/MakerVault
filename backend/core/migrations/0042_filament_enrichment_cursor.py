from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("core", "0041_component_enrichment_cursor")]

    operations = [
        migrations.AddField(
            model_name="cataloguemaintenancesettings",
            name="filament_enrichment_cursor",
            field=models.CharField(blank=True, default="", max_length=64),
        ),
    ]
