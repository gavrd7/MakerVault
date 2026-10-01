import uuid

from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0033_expand_multi_material_systems"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name="printerconnection",
            name="controls_enabled",
            field=models.BooleanField(default=False),
        ),
        migrations.CreateModel(
            name="PrinterControlRequest",
            fields=[
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("id", models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False, serialize=False)),
                ("action", models.CharField(max_length=10, choices=[("pause", "Pause"), ("resume", "Resume"), ("cancel", "Cancel")])),
                ("expected_job", models.CharField(max_length=64)),
                ("status", models.CharField(max_length=12, default="pending", choices=[("pending", "Pending"), ("sent", "Sent"), ("rejected", "Rejected"), ("unknown", "Unknown")])),
                ("message", models.TextField(blank=True)),
                ("connection", models.ForeignKey(to="core.printerconnection", on_delete=django.db.models.deletion.CASCADE, related_name="control_requests")),
                ("requested_by", models.ForeignKey(to=settings.AUTH_USER_MODEL, on_delete=django.db.models.deletion.CASCADE)),
            ],
        ),
    ]
