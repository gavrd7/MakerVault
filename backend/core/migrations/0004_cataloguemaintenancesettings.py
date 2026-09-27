from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0003_project_workspace_fields"),
    ]

    operations = [
        migrations.CreateModel(
            name="CatalogueMaintenanceSettings",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("singleton_key", models.PositiveSmallIntegerField(default=1, editable=False, unique=True)),
                ("enabled", models.BooleanField(default=True)),
                ("interval_hours", models.PositiveIntegerField(default=24)),
                ("check_board_data", models.BooleanField(default=True)),
                ("check_images", models.BooleanField(default=True)),
                ("last_run_at", models.DateTimeField(blank=True, null=True)),
                ("next_run_at", models.DateTimeField(blank=True, null=True)),
                ("last_triggered_by", models.CharField(blank=True, max_length=120)),
            ],
            options={
                "verbose_name": "Catalogue maintenance settings",
                "verbose_name_plural": "Catalogue maintenance settings",
            },
        ),
    ]
