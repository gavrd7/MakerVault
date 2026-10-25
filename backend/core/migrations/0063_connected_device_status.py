from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("core", "0062_connected_devices")]
    operations = [
        migrations.AddField(
            model_name="connecteddevice",
            name="reported_status",
            field=models.JSONField(blank=True, default=dict),
        ),
    ]
