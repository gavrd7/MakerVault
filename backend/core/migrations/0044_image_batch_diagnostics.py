from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("core", "0043_image_next_kind")]

    operations = [
        migrations.AddField(
            model_name="cataloguemaintenancesettings",
            name="image_last_batch_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="cataloguemaintenancesettings",
            name="image_last_batch_summary",
            field=models.JSONField(blank=True, default=dict),
        ),
    ]
