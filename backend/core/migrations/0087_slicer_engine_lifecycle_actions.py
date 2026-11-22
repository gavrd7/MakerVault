from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0086_printergcodesubmission_cfs_mapping_audit"),
    ]

    operations = [
        migrations.AlterField(
            model_name="slicerengineoperation",
            name="action",
            field=models.CharField(max_length=16, choices=[
                ("install", "Install"),
                ("update", "Update"),
                ("rollback", "Rollback"),
                ("activate", "Switch version"),
                ("uninstall", "Uninstall"),
            ]),
        ),
    ]
