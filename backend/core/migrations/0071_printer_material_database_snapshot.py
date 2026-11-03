import django.db.models.deletion
from django.db import migrations, models
import django.utils.timezone


class Migration(migrations.Migration):
    dependencies = [("core", "0070_unique_filament_manufacturer_casefold")]

    operations = [
        migrations.CreateModel(
            name="PrinterMaterialDatabaseSnapshot",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("payload", models.JSONField(default=dict)),
                ("synced_at", models.DateTimeField()),
                ("byte_size", models.PositiveIntegerField(default=0)),
                ("connection", models.OneToOneField(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name="material_database_copy", to="core.printerconnection",
                )),
            ],
        ),
    ]
