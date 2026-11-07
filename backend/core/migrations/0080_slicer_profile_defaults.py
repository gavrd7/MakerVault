from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("core", "0079_slicer_profile_verification")]

    operations = [
        migrations.AddField(
            model_name="slicerprofile",
            name="is_default",
            field=models.BooleanField(default=False, db_index=True),
        ),
    ]
