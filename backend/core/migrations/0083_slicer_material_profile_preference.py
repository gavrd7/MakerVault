from django.db import migrations, models
import django.db.models.deletion
import uuid


class Migration(migrations.Migration):
    dependencies = [("core", "0082_slicer_profile_source_scope")]

    operations = [
        migrations.CreateModel(
            name="SlicerMaterialProfilePreference",
            fields=[
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("id", models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False, serialize=False)),
                ("material_key", models.CharField(max_length=64)),
                ("engine", models.CharField(max_length=32)),
                ("engine_version", models.CharField(max_length=80)),
                ("printer", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE,
                    related_name="slicer_material_preferences", to="core.printer")),
                ("profile", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE,
                    related_name="material_preferences", to="core.slicerprofile")),
            ],
        ),
        migrations.AddConstraint(
            model_name="slicermaterialprofilepreference",
            constraint=models.UniqueConstraint(
                fields=["printer", "material_key", "engine", "engine_version"],
                name="unique_slicer_material_preference",
            ),
        ),
    ]
