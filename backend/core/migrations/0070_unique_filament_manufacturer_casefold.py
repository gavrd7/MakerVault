from django.db import migrations, models
from django.db.models.functions import Lower


class Migration(migrations.Migration):
    dependencies = [("core", "0069_merge_case_only_filament_manufacturers")]

    operations = [
        migrations.AddConstraint(
            model_name="filamentmanufacturer",
            constraint=models.UniqueConstraint(Lower("name"), name="unique_filament_manufacturer_casefold"),
        ),
    ]
