from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("core", "0084_slicer_engine_operation")]

    operations = [
        migrations.CreateModel(
            name="SlicerEngineAccessSettings",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True,
                    serialize=False, verbose_name="ID")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("restrict_engine_management_to_admins",
                 models.BooleanField(default=False)),
            ],
            options={"verbose_name": "Slicer engine access settings"},
        ),
    ]
