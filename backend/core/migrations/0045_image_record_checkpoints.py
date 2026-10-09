from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("core", "0044_image_batch_diagnostics")]

    operations = [
        migrations.AddField(
            model_name="cataloguemaintenancesettings",
            name="image_record_checkpoints",
            field=models.JSONField(blank=True, default=dict),
        ),
    ]
