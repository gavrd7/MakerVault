from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("core", "0058_reusable_spool_corrections")]

    operations = [
        migrations.AlterField(
            model_name="reusablespoolcatalogimageoverride",
            name="id",
            field=models.BigAutoField(primary_key=True, serialize=False),
        ),
        migrations.AlterField(
            model_name="reusablespoolcataloguesuggestion",
            name="id",
            field=models.BigAutoField(primary_key=True, serialize=False),
        ),
    ]
