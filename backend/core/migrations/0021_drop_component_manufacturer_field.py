from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0020_remove_component_manufacturer"),
    ]

    operations = [
        migrations.RemoveField(
            model_name="componentmodel",
            name="manufacturer",
        ),
    ]
