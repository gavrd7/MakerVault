from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0009_filament_transparency"),
    ]

    operations = [
        migrations.AddField(
            model_name="filamentproduct",
            name="color_hexes",
            field=models.JSONField(blank=True, default=list),
        ),
        migrations.AddField(
            model_name="filamentproduct",
            name="multi_color_direction",
            field=models.CharField(blank=True, max_length=24),
        ),
        migrations.AddField(
            model_name="filamentproduct",
            name="finish",
            field=models.CharField(blank=True, max_length=40),
        ),
        migrations.AddField(
            model_name="filamentproduct",
            name="pattern",
            field=models.CharField(blank=True, max_length=40),
        ),
        migrations.AddField(
            model_name="filamentproduct",
            name="glow",
            field=models.BooleanField(default=False),
        ),
    ]
