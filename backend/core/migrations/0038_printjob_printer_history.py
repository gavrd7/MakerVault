from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0037_filament_catalogue_enrichment"),
    ]

    operations = [
        migrations.AlterField(
            model_name="printjob",
            name="printer",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="print_jobs",
                to="core.printer",
            ),
        ),
    ]
