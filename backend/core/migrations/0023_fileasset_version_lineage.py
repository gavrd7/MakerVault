from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0022_merge_duplicate_components"),
    ]

    operations = [
        migrations.AddField(
            model_name="fileasset",
            name="supersedes",
            field=models.OneToOneField(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="superseded_by",
                to="core.fileasset",
            ),
        ),
    ]
