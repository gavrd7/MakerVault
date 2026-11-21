from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [("core", "0077_slicer_profile")]

    operations = [
        migrations.AddField(
            model_name="slicejob", name="printer_profile",
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="printer_slice_jobs", to="core.slicerprofile"),
        ),
        migrations.AddField(
            model_name="slicejob", name="filament_profile",
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="filament_slice_jobs", to="core.slicerprofile"),
        ),
        migrations.AddField(
            model_name="slicejob", name="process_profile",
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="process_slice_jobs", to="core.slicerprofile"),
        ),
    ]
