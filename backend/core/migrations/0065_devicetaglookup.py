import django.db.models.deletion
import uuid
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0064_devicetagregistration"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="DeviceTagLookup",
            fields=[
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("state", models.CharField(choices=[("pending", "Pending"), ("completed", "Completed"), ("cancelled", "Cancelled")], default="pending", max_length=12)),
                ("expires_at", models.DateTimeField()),
                ("completed_at", models.DateTimeField(blank=True, null=True)),
                ("scanned_uid", models.CharField(blank=True, max_length=24)),
                ("found", models.BooleanField(default=None, null=True)),
                ("device", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="tag_lookups", to="core.connecteddevice")),
                ("owner", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="device_tag_lookups", to=settings.AUTH_USER_MODEL)),
                ("tag", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, to="core.makertag")),
            ],
            options={"ordering": ["-created_at"], "indexes": [models.Index(fields=["device", "state", "expires_at"], name="tag_look_device_state_idx")]},
        ),
    ]
