import uuid

from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0028_private_encrypted_storage"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="MakerTag",
            fields=[
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("public_token", models.UUIDField(default=uuid.uuid4, editable=False, unique=True)),
                ("kind", models.CharField(choices=[("qr", "QR code"), ("nfc", "NFC tag"), ("rfid", "RFID tag")], default="qr", max_length=16)),
                ("code", models.CharField(max_length=255)),
                ("label", models.CharField(blank=True, max_length=200)),
                ("status", models.CharField(choices=[("active", "Active"), ("retired", "Retired")], default="active", max_length=16)),
                ("target_type", models.CharField(choices=[("inventory", "Inventory item"), ("spool", "Spool"), ("printer", "Printer"), ("project", "Project"), ("location", "Storage / printing location")], max_length=24)),
                ("target_id", models.UUIDField()),
                ("notes", models.TextField(blank=True)),
                ("metadata", models.JSONField(blank=True, default=dict)),
                ("retired_at", models.DateTimeField(blank=True, null=True)),
                ("owner", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="makervault_tags", to=settings.AUTH_USER_MODEL)),
            ],
            options={
                "ordering": ["status", "label", "kind", "code"],
            },
        ),
        migrations.CreateModel(
            name="MakerTagEvent",
            fields=[
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("event_type", models.CharField(choices=[("created", "Created"), ("assigned", "Assigned"), ("reassigned", "Reassigned"), ("retired", "Retired"), ("reactivated", "Reactivated"), ("updated", "Updated")], max_length=20)),
                ("summary", models.CharField(max_length=500)),
                ("details", models.JSONField(blank=True, default=dict)),
                ("changed_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="makervault_tag_events", to=settings.AUTH_USER_MODEL)),
                ("tag", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="events", to="core.makertag")),
            ],
            options={
                "ordering": ["-created_at"],
            },
        ),
        migrations.AddConstraint(
            model_name="makertag",
            constraint=models.UniqueConstraint(fields=("kind", "code"), name="unique_maker_tag_identity"),
        ),
        migrations.AddIndex(
            model_name="makertag",
            index=models.Index(fields=["owner", "target_type", "target_id"], name="maker_tag_target_idx"),
        ),
    ]
