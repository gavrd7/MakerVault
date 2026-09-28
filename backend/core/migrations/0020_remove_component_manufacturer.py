from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0019_external_printer_links_simplyprint_slots"),
    ]

    operations = [
        migrations.RemoveField(
            model_name="componentmodel",
            name="manufacturer",
        ),
    ]
