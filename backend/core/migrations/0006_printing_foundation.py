import uuid

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0005_bom_allocations"),
    ]

    operations = [
        migrations.CreateModel(
            name="ExternalSpoolLink",
            fields=[
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("provider", models.CharField(choices=[("spoolman", "Spoolman"), ("simplyprint", "SimplyPrint"), ("other", "Other")], max_length=30)),
                ("external_id", models.CharField(max_length=255)),
                ("external_url", models.URLField(blank=True)),
                ("sync_direction", models.CharField(choices=[("import", "External → MakerVault"), ("export", "MakerVault → external"), ("bidirectional", "Bidirectional")], default="import", max_length=20)),
                ("last_synced_at", models.DateTimeField(blank=True, null=True)),
                ("sync_metadata", models.JSONField(blank=True, default=dict)),
                ("spool", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="external_links", to="core.spool")),
            ],
            options={"ordering": ["provider", "external_id"]},
        ),
        migrations.CreateModel(
            name="PrinterFilamentSlot",
            fields=[
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("system", models.CharField(choices=[("creality_cfs", "Creality CFS"), ("bambu_ams", "Bambu Lab AMS"), ("elegoo", "Elegoo multi-material"), ("qidi", "QIDI multi-material"), ("snapmaker", "Snapmaker multi-material"), ("generic", "Generic / other")], default="generic", max_length=30)),
                ("unit_index", models.PositiveSmallIntegerField(default=0)),
                ("slot_index", models.PositiveSmallIntegerField(default=0)),
                ("external_ref", models.CharField(blank=True, max_length=255)),
                ("rfid_uid", models.CharField(blank=True, db_index=True, max_length=255)),
                ("material", models.CharField(blank=True, max_length=80)),
                ("color_name", models.CharField(blank=True, max_length=120)),
                ("color_hex", models.CharField(blank=True, max_length=9)),
                ("remaining_weight_g", models.DecimalField(blank=True, decimal_places=2, max_digits=10, null=True)),
                ("is_loaded", models.BooleanField(default=True)),
                ("last_seen_at", models.DateTimeField(blank=True, null=True)),
                ("metadata", models.JSONField(blank=True, default=dict)),
                ("printer", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="filament_slots", to="core.printer")),
                ("spool", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="printer_slots", to="core.spool")),
            ],
            options={"ordering": ["printer__name", "system", "unit_index", "slot_index"]},
        ),
        migrations.CreateModel(
            name="ModelRevisionAsset",
            fields=[
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("role", models.CharField(choices=[("model", "Printable model"), ("slicer", "Slicer project"), ("cad", "CAD / source"), ("reference", "Reference"), ("other", "Other")], default="model", max_length=20)),
                ("is_primary", models.BooleanField(default=False)),
                ("notes", models.TextField(blank=True)),
                ("file_asset", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="model_revisions", to="core.fileasset")),
                ("revision", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="assets", to="core.modelrevision")),
            ],
            options={"ordering": ["role", "-is_primary", "created_at"]},
        ),
        migrations.AddConstraint(
            model_name="externalspoollink",
            constraint=models.UniqueConstraint(fields=("provider", "external_id"), name="unique_external_spool_provider_id"),
        ),
        migrations.AddConstraint(
            model_name="externalspoollink",
            constraint=models.UniqueConstraint(fields=("spool", "provider"), name="unique_spool_provider_link"),
        ),
        migrations.AddConstraint(
            model_name="printerfilamentslot",
            constraint=models.UniqueConstraint(fields=("printer", "system", "unit_index", "slot_index"), name="unique_printer_filament_slot"),
        ),
        migrations.AddConstraint(
            model_name="modelrevisionasset",
            constraint=models.UniqueConstraint(fields=("revision", "file_asset"), name="unique_revision_file_asset"),
        ),
    ]
}
