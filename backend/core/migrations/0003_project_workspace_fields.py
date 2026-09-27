from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0002_inventoryhistory"),
    ]

    operations = [
        migrations.AddField(
            model_name="project",
            name="notes",
            field=models.TextField(blank=True),
        ),
        migrations.AddField(
            model_name="project",
            name="reference_url",
            field=models.URLField(blank=True),
        ),
        migrations.AddField(
            model_name="project",
            name="tags",
            field=models.JSONField(blank=True, default=list),
        ),
    ]
