from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0008_print_material_usage"),
    ]

    operations = [
        migrations.AddField(
            model_name="filamentproduct",
            name="transparency",
            field=models.CharField(
                choices=[
                    ("opaque", "Opaque"),
                    ("translucent", "Translucent"),
                    ("transparent", "Transparent"),
                ],
                default="opaque",
                max_length=16,
            ),
        ),
    ]
