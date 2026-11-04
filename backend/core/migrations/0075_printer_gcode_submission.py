import uuid
from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0074_fileasset_gcode_category"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="PrinterGcodeSubmission",
            fields=[
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("id", models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False, serialize=False)),
                ("source", models.CharField(max_length=20)),
                ("action", models.CharField(max_length=12)),
                ("original_path", models.CharField(max_length=512, blank=True)),
                ("remote_path", models.CharField(max_length=512, blank=True)),
                ("file_sha256", models.CharField(max_length=64, blank=True)),
                ("status", models.CharField(max_length=12, choices=[
                    ("pending", "Pending"), ("uploaded", "Uploaded"),
                    ("started", "Start requested"), ("rejected", "Rejected"),
                    ("unknown", "Outcome unknown"),
                ], default="pending")),
                ("message", models.TextField(blank=True)),
                ("connection", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="gcode_submissions", to="core.printerconnection")),
                ("file_asset", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="printer_submissions", to="core.fileasset")),
                ("requested_by", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="gcode_submissions", to=settings.AUTH_USER_MODEL)),
            ],
            options={"ordering": ["-created_at"]},
        ),
    ]
