from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("core", "0055_personal_spool_images")]

    operations = [
        migrations.AlterField(
            model_name="reusablespooldesign",
            name="image",
            field=models.ImageField(blank=True, null=True, upload_to="catalogue/reusable-spools/personal-designs/"),
        ),
        migrations.AlterField(
            model_name="reusablespoolcatalogimageoverride",
            name="image",
            field=models.ImageField(upload_to="catalogue/reusable-spools/personal-catalogue/"),
        ),
    ]
