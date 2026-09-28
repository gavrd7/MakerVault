from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0012_printing_integration_sync_schedule"),
    ]

    operations = [
        migrations.AddField(
            model_name="spool",
            name="rfid_uid",
            field=models.CharField(blank=True, db_index=True, default="", max_length=255),
        ),
        migrations.AddConstraint(
            model_name="spool",
            constraint=models.UniqueConstraint(
                condition=~models.Q(rfid_uid=""),
                fields=("rfid_uid",),
                name="unique_nonblank_spool_rfid_uid",
            ),
        ),
    ]
