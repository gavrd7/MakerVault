from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion
import uuid


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0083_slicer_material_profile_preference"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="SlicerEngineOperation",
            fields=[
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("id", models.UUIDField(primary_key=True, default=uuid.uuid4,
                                       editable=False, serialize=False)),
                ("engine", models.CharField(max_length=32)),
                ("version", models.CharField(max_length=80)),
                ("action", models.CharField(max_length=16, choices=[
                    ("install", "Install"), ("update", "Update"), ("rollback", "Rollback")])),
                ("release_sha256", models.CharField(max_length=64)),
                ("status", models.CharField(max_length=16, default="queued", choices=[
                    ("queued", "Queued"), ("downloading", "Downloading"),
                    ("verifying", "Verifying"), ("staged", "Staged"),
                    ("activating", "Activating"), ("completed", "Completed"),
                    ("failed", "Failed"), ("cancelled", "Cancelled")])),
                ("progress", models.PositiveSmallIntegerField(default=0)),
                ("status_message", models.CharField(max_length=200, blank=True)),
                ("completed_at", models.DateTimeField(null=True, blank=True)),
                ("requested_by", models.ForeignKey(to=settings.AUTH_USER_MODEL,
                    on_delete=django.db.models.deletion.PROTECT,
                    related_name="slicer_engine_operations")),
            ],
            options={"ordering": ("-created_at",)},
        ),
        migrations.AddIndex(
            model_name="slicerengineoperation",
            index=models.Index(fields=["status", "created_at"],
                               name="slicer_engine_op_queue_idx"),
        ),
    ]
