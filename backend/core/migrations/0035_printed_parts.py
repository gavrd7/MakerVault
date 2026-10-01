import uuid
from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [("core", "0034_printer_controls"), migrations.swappable_dependency(settings.AUTH_USER_MODEL)]
    operations = [
        migrations.CreateModel(
            name="PrintedPart",
            fields=[
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("id", models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False, serialize=False)),
                ("name", models.CharField(max_length=200)),
                ("quantity", models.PositiveIntegerField(default=1)),
                ("status", models.CharField(max_length=20, default="available", choices=[("available", "Available"), ("installed", "Installed / in use"), ("spare", "Spare"), ("failed", "Failed"), ("scrapped", "Scrapped"), ("retired", "Retired")])),
                ("production", models.JSONField(default=dict, blank=True)),
                ("notes", models.TextField(blank=True)),
                ("owner", models.ForeignKey(to=settings.AUTH_USER_MODEL, on_delete=django.db.models.deletion.CASCADE, related_name="makervault_printed_parts")),
                ("print_job", models.ForeignKey(to="core.printjob", on_delete=django.db.models.deletion.SET_NULL, null=True, blank=True, related_name="printed_parts")),
                ("model_revision", models.ForeignKey(to="core.modelrevision", on_delete=django.db.models.deletion.SET_NULL, null=True, blank=True, related_name="printed_parts")),
                ("project", models.ForeignKey(to="core.project", on_delete=django.db.models.deletion.SET_NULL, null=True, blank=True, related_name="printed_parts")),
                ("location", models.ForeignKey(to="core.printinglocation", on_delete=django.db.models.deletion.SET_NULL, null=True, blank=True, related_name="printed_parts")),
                ("replaces", models.ForeignKey(to="core.printedpart", on_delete=django.db.models.deletion.SET_NULL, null=True, blank=True, related_name="replacements")),
            ],
            options={"ordering": ["-created_at"], "constraints": [models.CheckConstraint(condition=models.Q(quantity__gte=1), name="printed_part_quantity_positive")]},
        ),
        migrations.CreateModel(
            name="PrintedPartEvent",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("changes", models.JSONField(default=dict)),
                ("part", models.ForeignKey(to="core.printedpart", on_delete=django.db.models.deletion.CASCADE, related_name="events")),
                ("changed_by", models.ForeignKey(to=settings.AUTH_USER_MODEL, on_delete=django.db.models.deletion.SET_NULL, null=True)),
            ],
            options={"ordering": ["-created_at", "-id"]},
        ),
        migrations.AlterField(model_name="makertag", name="target_type", field=models.CharField(max_length=24, choices=[("printed_part", "Printed part"), ("inventory", "Inventory item"), ("spool", "Spool"), ("printer", "Printer"), ("project", "Project"), ("location", "Storage / printing location")])),
    ]
