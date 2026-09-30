import uuid

from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0029_maker_tags"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="WiringDiagram",
            fields=[
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("name", models.CharField(max_length=255)),
                ("description", models.TextField(blank=True)),
                ("nodes", models.JSONField(blank=True, default=list)),
                ("connections", models.JSONField(blank=True, default=list)),
                ("canvas", models.JSONField(blank=True, default=dict)),
                ("revision", models.PositiveIntegerField(default=1)),
                ("owner", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="makervault_wiring_diagrams", to=settings.AUTH_USER_MODEL)),
                ("project", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="wiring_diagrams", to="core.project")),
            ],
            options={
                "ordering": ["name", "-updated_at"],
            },
        ),
        migrations.AddConstraint(
            model_name="wiringdiagram",
            constraint=models.UniqueConstraint(fields=("project", "name"), name="uniq_wiring_diagram_name_per_project"),
        ),
    ]
