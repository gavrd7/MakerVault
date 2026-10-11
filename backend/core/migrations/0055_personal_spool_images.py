import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0054_reusable_spool_variants"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]
    operations = [
        migrations.AddField(
            model_name="reusablespooldesign",
            name="image",
            field=models.ImageField(blank=True, null=True, upload_to="user/reusable-spool-designs/"),
        ),
        migrations.CreateModel(
            name="ReusableSpoolCatalogImageOverride",
            fields=[
                ("id", models.BigAutoField(primary_key=True, serialize=False)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("image", models.ImageField(upload_to="user/reusable-spool-catalogue/")),
                ("catalog_entry", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to="core.reusablespoolcatalogentry")),
                ("owner", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to=settings.AUTH_USER_MODEL)),
            ],
        ),
        migrations.AddConstraint(
            model_name="reusablespoolcatalogimageoverride",
            constraint=models.UniqueConstraint(fields=("owner", "catalog_entry"), name="unique_owned_spool_catalogue_image"),
        ),
    ]
