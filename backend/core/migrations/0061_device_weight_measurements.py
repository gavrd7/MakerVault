from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion
import django.utils.timezone
import uuid


class Migration(migrations.Migration):
    dependencies = [("core", "0060_user_api_keys"), migrations.swappable_dependency(settings.AUTH_USER_MODEL)]

    operations = [
        migrations.CreateModel(
            name="DeviceWeightMeasurement",
            fields=[
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("id", models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False, serialize=False)),
                ("request_id", models.UUIDField()),
                ("target_type", models.CharField(max_length=24)),
                ("target_id", models.UUIDField()),
                ("gross_weight_g", models.DecimalField(max_digits=10, decimal_places=2)),
                ("tare_weight_g", models.DecimalField(max_digits=10, decimal_places=2)),
                ("net_weight_g", models.DecimalField(max_digits=10, decimal_places=2)),
                ("updated_spool", models.BooleanField(default=False)),
                ("previous_spool_weight_g", models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)),
                ("recorded_at", models.DateTimeField(default=django.utils.timezone.now)),
                ("owner", models.ForeignKey(to=settings.AUTH_USER_MODEL, on_delete=django.db.models.deletion.CASCADE, related_name="device_weight_measurements")),
                ("api_key", models.ForeignKey(to="core.userapikey", on_delete=django.db.models.deletion.SET_NULL, blank=True, null=True)),
            ],
            options={"ordering": ["-recorded_at"]},
        ),
        migrations.AddConstraint(
            model_name="deviceweightmeasurement",
            constraint=models.UniqueConstraint(fields=("owner", "request_id"), name="uniq_device_weight_request"),
        ),
    ]
