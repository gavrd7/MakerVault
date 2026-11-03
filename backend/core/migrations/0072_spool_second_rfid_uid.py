from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("core", "0071_printer_material_database_snapshot")]

    operations = [
        migrations.AddField(
            model_name="spool", name="rfid_uid_secondary",
            field=models.CharField(blank=True, db_index=True, default="", max_length=255),
        ),
        migrations.AddConstraint(
            model_name="spool",
            constraint=models.UniqueConstraint(
                fields=("rfid_uid_secondary",),
                condition=~models.Q(rfid_uid_secondary=""),
                name="uniq_nonblank_spool_rfid_second",
            ),
        ),
    ]
