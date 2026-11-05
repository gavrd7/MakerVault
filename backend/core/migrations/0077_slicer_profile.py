import uuid
from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0076_slice_job"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="SlicerProfile",
            fields=[
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("engine", models.CharField(max_length=32)),
                ("engine_version", models.CharField(max_length=80)),
                ("kind", models.CharField(choices=[("printer", "Printer"), ("filament", "Filament"), ("process", "Process")], max_length=16)),
                ("name", models.CharField(max_length=200)),
                ("content_sha256", models.CharField(max_length=64)),
                ("status", models.CharField(choices=[("candidate", "Not verified"), ("verified", "Verified for worker")], default="candidate", max_length=16)),
                ("provenance", models.CharField(blank=True, max_length=200)),
                ("file_asset", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="slicer_profile_links", to="core.fileasset")),
                ("owner", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="slicer_profiles", to=settings.AUTH_USER_MODEL)),
            ],
            options={"ordering": ["engine", "kind", "name", "-created_at"]},
        ),
        migrations.AddConstraint(
            model_name="slicerprofile",
            constraint=models.UniqueConstraint(
                fields=("owner", "engine", "engine_version", "kind", "name"),
                name="unique_slicer_profile_identity",
            ),
        ),
    ]
