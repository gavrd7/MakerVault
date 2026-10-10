from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("core", "0046_reusable_spool_inventory")]

    operations = [
        migrations.AddField(
            model_name="reusablespool",
            name="color_hex",
            field=models.CharField(blank=True, max_length=7),
        ),
    ]
