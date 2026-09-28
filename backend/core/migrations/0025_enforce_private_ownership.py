from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0024_user_ownership_storage_profile"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.RemoveConstraint(
            model_name="externalspoollink",
            name="unique_external_spool_provider_id",
        ),
        migrations.RemoveConstraint(
            model_name="externalprinterlink",
            name="unique_external_printer_provider_id",
        ),
        migrations.AlterField(
            model_name="project",
            name="owner",
            field=models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="owned_makervault_projects", to=settings.AUTH_USER_MODEL),
        ),
        migrations.AlterField(model_name="project", name="slug", field=models.SlugField(blank=True, max_length=280)),
        migrations.AddConstraint(
            model_name="project",
            constraint=models.UniqueConstraint(fields=("owner", "slug"), name="uniq_project_slug_per_owner"),
        ),
        migrations.AlterField(
            model_name="inventoryitem",
            name="owner",
            field=models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="makervault_inventory_items", to=settings.AUTH_USER_MODEL),
        ),
        migrations.AlterField(model_name="inventoryitem", name="inventory_id", field=models.CharField(max_length=40)),
        migrations.AddConstraint(
            model_name="inventoryitem",
            constraint=models.UniqueConstraint(fields=("owner", "inventory_id"), name="uniq_inventory_id_per_owner"),
        ),
        migrations.AlterField(
            model_name="fileasset",
            name="owner",
            field=models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="makervault_file_assets", to=settings.AUTH_USER_MODEL),
        ),
        migrations.AlterField(
            model_name="printinglocation",
            name="owner",
            field=models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="makervault_printing_locations", to=settings.AUTH_USER_MODEL),
        ),
        migrations.AlterField(model_name="printinglocation", name="name", field=models.CharField(max_length=200)),
        migrations.AddConstraint(
            model_name="printinglocation",
            constraint=models.UniqueConstraint(fields=("owner", "name"), name="uniq_print_location_per_owner"),
        ),
        migrations.AlterField(
            model_name="printingintegrationsetting",
            name="owner",
            field=models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="makervault_printing_integrations", to=settings.AUTH_USER_MODEL),
        ),
        migrations.AlterField(
            model_name="printingintegrationsetting",
            name="provider",
            field=models.CharField(choices=[("spoolman", "Spoolman"), ("simplyprint", "SimplyPrint"), ("creality_cfs", "Creality CFS"), ("bambu_ams", "Bambu Lab AMS"), ("elegoo", "Elegoo multi-material"), ("qidi", "QIDI multi-material"), ("snapmaker", "Snapmaker multi-material")], max_length=30),
        ),
        migrations.AddConstraint(
            model_name="printingintegrationsetting",
            constraint=models.UniqueConstraint(fields=("owner", "provider"), name="uniq_print_integration_per_owner"),
        ),
        migrations.AlterField(
            model_name="spool",
            name="owner",
            field=models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="makervault_spools", to=settings.AUTH_USER_MODEL),
        ),
        migrations.AlterField(model_name="spool", name="spool_id", field=models.CharField(max_length=40)),
        migrations.AddConstraint(
            model_name="spool",
            constraint=models.UniqueConstraint(fields=("owner", "spool_id"), name="uniq_spool_id_per_owner"),
        ),
        migrations.AlterField(
            model_name="printer",
            name="owner",
            field=models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="makervault_printers", to=settings.AUTH_USER_MODEL),
        ),
        migrations.AlterField(
            model_name="model3d",
            name="owner",
            field=models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="makervault_models_3d", to=settings.AUTH_USER_MODEL),
        ),
        migrations.AlterField(
            model_name="printjob",
            name="owner",
            field=models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="makervault_print_jobs", to=settings.AUTH_USER_MODEL),
        ),
    ]
