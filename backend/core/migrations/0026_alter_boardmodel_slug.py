from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0025_enforce_private_ownership"),
    ]

    operations = [
        migrations.AlterField(
            model_name="boardmodel",
            name="slug",
            field=models.SlugField(blank=True, max_length=280),
        ),
    ]
