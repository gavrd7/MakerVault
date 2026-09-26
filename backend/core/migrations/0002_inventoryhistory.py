import uuid
from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0001_initial"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="InventoryHistory",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("event_type", models.CharField(choices=[
                    ("created", "Added to inventory"),
                    ("updated", "Updated"),
                    ("assigned", "Assigned to project"),
                    ("unassigned", "Removed from project"),
                    ("status", "Status changed"),
                    ("location", "Location changed"),
                ], default="updated", max_length=20)),
                ("summary", models.CharField(max_length=500)),
                ("changes", models.JSONField(blank=True, default=dict)),
                ("changed_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="makervault_inventory_changes", to=settings.AUTH_USER_MODEL)),
                ("inventory_item", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="history", to="core.inventoryitem")),
                ("project", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="inventory_history", to="core.project")),
            ],
            options={"ordering": ["-created_at"]},
        ),
    ]
