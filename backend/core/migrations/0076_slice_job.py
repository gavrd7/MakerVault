import uuid

from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0075_printer_gcode_submission"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="SliceJob",
            fields=[
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("engine", models.CharField(max_length=32)),
                ("engine_version", models.CharField(max_length=80)),
                ("printer_preset", models.CharField(max_length=200)),
                ("filament_preset", models.CharField(max_length=200)),
                ("process_preset", models.CharField(max_length=200)),
                ("nozzle_mm", models.DecimalField(decimal_places=2, max_digits=5)),
                ("plate", models.CharField(default="default", max_length=80)),
                ("settings", models.JSONField(blank=True, default=dict)),
                ("status", models.CharField(choices=[("draft", "Draft"), ("queued", "Queued"), ("running", "Running"), ("completed", "Completed"), ("failed", "Failed"), ("cancelled", "Cancelled"), ("stale", "Stale")], db_index=True, default="draft", max_length=16)),
                ("progress", models.PositiveSmallIntegerField(default=0)),
                ("message", models.CharField(blank=True, max_length=255)),
                ("input_asset", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="slice_inputs", to="core.fileasset")),
                ("output_asset", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="slice_outputs", to="core.fileasset")),
                ("owner", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="slicing_jobs", to=settings.AUTH_USER_MODEL)),
                ("printer", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="slice_jobs", to="core.printer")),
                ("spool", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="slice_jobs", to="core.spool")),
            ],
            options={"ordering": ["-created_at"]},
        ),
        migrations.AddIndex(
            model_name="slicejob",
            index=models.Index(fields=["owner", "status"], name="slice_owner_status_idx"),
        ),
    ]
