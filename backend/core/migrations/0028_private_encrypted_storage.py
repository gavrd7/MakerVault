import core.private_storage
import core.validators
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0027_storagesettings_default_quota_unlimited"),
    ]

    operations = [
        migrations.AlterField(
            model_name="fileasset",
            name="file",
            field=models.FileField(
                storage=core.private_storage.PrivateEncryptedStorage(),
                upload_to="files/%Y/%m/",
                validators=[core.validators.validate_maker_file],
            ),
        ),
        migrations.AlterField(
            model_name="inventoryitem",
            name="image",
            field=models.ImageField(
                blank=True,
                null=True,
                storage=core.private_storage.PrivateEncryptedStorage(),
                upload_to="inventory/",
            ),
        ),
        migrations.AlterField(
            model_name="project",
            name="cover_image",
            field=models.ImageField(
                blank=True,
                null=True,
                storage=core.private_storage.PrivateEncryptedStorage(),
                upload_to="projects/covers/",
            ),
        ),
    ]
