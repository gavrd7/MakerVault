from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0030_wiring_diagrams"),
    ]

    operations = [
        migrations.AlterField(
            model_name="wiringdiagram",
            name="project",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="wiring_diagrams",
                to="core.project",
            ),
        ),
        migrations.AddConstraint(
            model_name="wiringdiagram",
            constraint=models.UniqueConstraint(
                condition=models.Q(("project__isnull", True)),
                fields=("owner", "name"),
                name="uniq_standalone_wiring_name_per_owner",
            ),
        ),
    ]
