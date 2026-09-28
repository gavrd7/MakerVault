import uuid

from django.db import migrations, models
import django.db.models.deletion


def migrate_legacy_print_material_usage(apps, schema_editor):
    PrintJob = apps.get_model("core", "PrintJob")
    PrintMaterialUsage = apps.get_model("core", "PrintMaterialUsage")
    Spool = apps.get_model("core", "Spool")

    for job in PrintJob.objects.all().iterator():
        has_usage = any([
            job.spool_id,
            job.filament_used_g is not None,
            job.waste_g is not None,
            job.material_cost is not None,
        ])
        if not has_usage:
            continue

        filament_id = None
        if job.spool_id:
            filament_id = Spool.objects.filter(pk=job.spool_id).values_list("filament_id", flat=True).first()

        PrintMaterialUsage.objects.create(
            print_job_id=job.pk,
            spool_id=job.spool_id,
            filament_id=filament_id,
            used_g=job.filament_used_g or 0,
            waste_g=job.waste_g or 0,
            material_cost=job.material_cost,
            currency=job.currency or "GBP",
            source_metadata={"migrated_from": "legacy PrintJob material fields"},
        )


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0007_modelrevision_fileasset_unification"),
    ]

    operations = [
        migrations.CreateModel(
            name="PrintMaterialUsage",
            fields=[
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("used_g", models.DecimalField(decimal_places=2, default=0, max_digits=10)),
                ("waste_g", models.DecimalField(decimal_places=2, default=0, max_digits=10)),
                ("material_cost", models.DecimalField(blank=True, decimal_places=2, max_digits=12, null=True)),
                ("currency", models.CharField(default="GBP", max_length=3)),
                ("notes", models.TextField(blank=True)),
                ("source_metadata", models.JSONField(blank=True, default=dict)),
                ("filament", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="print_material_usages", to="core.filamentproduct")),
                ("print_job", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="material_usages", to="core.printjob")),
                ("printer_slot", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="print_material_usages", to="core.printerfilamentslot")),
                ("spool", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="print_material_usages", to="core.spool")),
            ],
            options={"ordering": ["created_at"]},
        ),
        migrations.RunPython(migrate_legacy_print_material_usage, migrations.RunPython.noop),
        migrations.RemoveField(model_name="printjob", name="spool"),
        migrations.RemoveField(model_name="printjob", name="filament_used_g"),
        migrations.RemoveField(model_name="printjob", name="waste_g"),
        migrations.RemoveField(model_name="printjob", name="material_cost"),
        migrations.AddConstraint(
            model_name="printmaterialusage",
            constraint=models.CheckConstraint(condition=models.Q(("used_g__gte", 0)), name="print_material_used_nonnegative"),
        ),
        migrations.AddConstraint(
            model_name="printmaterialusage",
            constraint=models.CheckConstraint(condition=models.Q(("waste_g__gte", 0)), name="print_material_waste_nonnegative"),
        ),
    ]
