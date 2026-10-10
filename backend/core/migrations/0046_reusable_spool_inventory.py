# Reusable empty spool hardware is distinct from the existing filament-stock Spool.
import uuid

from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0045_image_record_checkpoints"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="ReusableSpoolDesign",
            fields=[
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("name", models.CharField(max_length=200)),
                ("manufacturer", models.CharField(blank=True, max_length=120)),
                ("design_type", models.CharField(choices=[("manufacturer", "Manufacturer-made"), ("printed", "3D printed")], default="printed", max_length=20)),
                ("description", models.TextField(blank=True)),
                ("source_url", models.URLField(blank=True)),
                ("material", models.CharField(blank=True, max_length=80)),
                ("nominal_tare_g", models.DecimalField(blank=True, decimal_places=2, max_digits=8, null=True)),
                ("max_dryer_temp_c", models.PositiveSmallIntegerField(blank=True, null=True)),
                ("temperature_source", models.CharField(blank=True, max_length=255)),
                ("outer_diameter_mm", models.DecimalField(blank=True, decimal_places=2, max_digits=7, null=True)),
                ("width_mm", models.DecimalField(blank=True, decimal_places=2, max_digits=7, null=True)),
                ("hub_diameter_mm", models.DecimalField(blank=True, decimal_places=2, max_digits=7, null=True)),
                ("capacity_g", models.DecimalField(blank=True, decimal_places=2, max_digits=8, null=True)),
                ("model_3d", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="reusable_spool_designs", to="core.model3d")),
                ("owner", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="reusable_spool_designs", to=settings.AUTH_USER_MODEL)),
            ],
            options={"ordering": ["name", "created_at"]},
        ),
        migrations.CreateModel(
            name="ReusableSpool",
            fields=[
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("code", models.CharField(max_length=40)),
                ("measured_tare_g", models.DecimalField(blank=True, decimal_places=2, max_digits=8, null=True)),
                ("color_name", models.CharField(blank=True, max_length=80)),
                ("material_override", models.CharField(blank=True, max_length=80)),
                ("notes", models.TextField(blank=True)),
                ("design", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="owned_spools", to="core.reusablespooldesign")),
                ("filament_spool", models.OneToOneField(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="reusable_reel", to="core.spool")),
                ("owner", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="reusable_spools", to=settings.AUTH_USER_MODEL)),
                ("storage_location", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="reusable_spools", to="core.printinglocation")),
            ],
            options={"ordering": ["code"]},
        ),
        migrations.AddConstraint(
            model_name="reusablespool",
            constraint=models.UniqueConstraint(fields=("owner", "code"), name="uniq_reusable_spool_code_per_owner"),
        ),
    ]
