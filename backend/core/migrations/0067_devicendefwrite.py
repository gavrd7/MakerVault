import django.db.models.deletion
import uuid
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0066_makertag_short_id"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="DeviceNdefWrite",
            fields=[
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("expected_uid", models.CharField(max_length=24)),
                ("url", models.CharField(max_length=300)),
                ("state", models.CharField(choices=[("pending", "Pending"), ("completed", "Completed"), ("cancelled", "Cancelled")], default="pending", max_length=12)),
                ("expires_at", models.DateTimeField()),
                ("completed_at", models.DateTimeField(blank=True, null=True)),
                ("device", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="ndef_writes", to="core.connecteddevice")),
                ("owner", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="device_ndef_writes", to=settings.AUTH_USER_MODEL)),
                ("tag", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="ndef_writes", to="core.makertag")),
            ],
            options={"ordering": ["-created_at"], "indexes": [models.Index(fields=["device", "state", "expires_at"], name="ndef_device_state_idx")]},
        )
    ]
