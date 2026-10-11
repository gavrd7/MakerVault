from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("core", "0051_spool_catalogue_maintenance_setting")]

    operations = [
        migrations.AlterField(
            model_name="makertag",
            name="target_type",
            field=models.CharField(
                max_length=24,
                choices=[
                    ("printed_part", "Printed part"),
                    ("inventory", "Inventory item"),
                    ("spool", "Spool"),
                    ("reusable_spool", "Reusable spool"),
                    ("printer", "Printer"),
                    ("project", "Project"),
                    ("location", "Storage / printing location"),
                ],
            ),
        ),
    ]
