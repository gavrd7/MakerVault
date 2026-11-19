from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0085_slicer_engine_access_settings"),
    ]

    operations = [
        migrations.AddField(
            model_name="printergcodesubmission",
            name="cfs_mapping_audit",
            field=models.JSONField(blank=True, default=dict),
        ),
    ]
