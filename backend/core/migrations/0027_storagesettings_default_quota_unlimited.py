from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0026_alter_boardmodel_slug"),
    ]

    operations = [
        migrations.AddField(
            model_name="storagesettings",
            name="default_quota_unlimited",
            field=models.BooleanField(default=False),
        ),
    ]
