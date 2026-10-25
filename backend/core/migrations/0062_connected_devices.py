from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion
import uuid


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0061_device_weight_measurements"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="ConnectedDevice",
            fields=[
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("id", models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False, serialize=False)),
                ("device_uid", models.CharField(max_length=120, unique=True)),
                ("name", models.CharField(max_length=120)),
                ("device_type", models.CharField(max_length=24, choices=[("rfid_terminal", "RFID/NFC terminal"), ("filament_scale", "Filament weighing station")])),
                ("firmware_version", models.CharField(max_length=80, blank=True)),
                ("capabilities", models.JSONField(default=list, blank=True)),
                ("last_seen_at", models.DateTimeField(null=True, blank=True)),
                ("revoked_at", models.DateTimeField(null=True, blank=True)),
                ("owner", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="connected_devices", to=settings.AUTH_USER_MODEL)),
                ("api_key", models.OneToOneField(null=True, blank=True, on_delete=django.db.models.deletion.SET_NULL, related_name="connected_device", to="core.userapikey")),
            ],
            options={"ordering": ["name", "created_at"]},
        ),
        migrations.CreateModel(
            name="DevicePairing",
            fields=[
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("id", models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False, serialize=False)),
                ("device_uid", models.CharField(max_length=120)),
                ("device_type", models.CharField(max_length=24, choices=[("rfid_terminal", "RFID/NFC terminal"), ("filament_scale", "Filament weighing station")])),
                ("claim_digest", models.CharField(max_length=64)),
                ("confirmation_code", models.CharField(max_length=8, unique=True)),
                ("expires_at", models.DateTimeField()),
                ("approved_name", models.CharField(max_length=120, blank=True)),
                ("approved_scopes", models.JSONField(default=list)),
                ("consumed_at", models.DateTimeField(null=True, blank=True)),
                ("approved_by", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, null=True, blank=True, to=settings.AUTH_USER_MODEL)),
            ],
            options={"ordering": ["-created_at"]},
        ),
    ]
