from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("core", "0078_slice_native_profiles")]

    operations = [
        migrations.AddField(
            model_name="slicerprofile",
            name="verification_evidence",
            field=models.JSONField(default=dict, blank=True),
        ),
        migrations.AddField(
            model_name="slicerprofile",
            name="verified_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]
