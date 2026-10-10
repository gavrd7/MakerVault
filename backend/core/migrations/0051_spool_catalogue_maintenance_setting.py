from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("core", "0050_reusable_spool_expanded_manufacturers")]

    operations = [
        migrations.AddField(
            model_name="cataloguemaintenancesettings",
            name="check_reusable_spool_sources",
            field=models.BooleanField(default=True),
        ),
    ]
