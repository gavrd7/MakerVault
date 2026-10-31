from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [("core", "0067_devicendefwrite")]

    operations = [
        migrations.AddField(
            model_name="devicetagregistration",
            name="ndef_origin",
            field=models.CharField(blank=True, default="", max_length=220),
        ),
        migrations.AddField(
            model_name="devicetagregistration",
            name="ndef_write",
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, to="core.devicendefwrite"),
        ),
    ]
