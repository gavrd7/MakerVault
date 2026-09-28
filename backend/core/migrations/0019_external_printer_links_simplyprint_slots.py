from django.db import migrations, models
import django.db.models.deletion
import uuid


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0018_printer_catalogue_enclosure_unknown"),
    ]

    operations = [
        migrations.CreateModel(
            name="ExternalPrinterLink",
            fields=[
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("provider", models.CharField(choices=[("simplyprint", "SimplyPrint"), ("other", "Other")], max_length=30)),
                ("external_id", models.CharField(max_length=255)),
                ("external_url", models.URLField(blank=True)),
                ("last_synced_at", models.DateTimeField(blank=True, null=True)),
                ("sync_metadata", models.JSONField(blank=True, default=dict)),
                ("printer", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="external_links", to="core.printer")),
            ],
            options={
                "ordering": ["provider", "external_id"],
            },
        ),
        migrations.AddConstraint(
            model_name="externalprinterlink",
            constraint=models.UniqueConstraint(fields=("provider", "external_id"), name="unique_external_printer_provider_id"),
        ),
        migrations.AddConstraint(
            model_name="externalprinterlink",
            constraint=models.UniqueConstraint(fields=("printer", "provider"), name="unique_printer_provider_link"),
        ),
        migrations.AlterField(
            model_name="printerfilamentslot",
            name="system",
            field=models.CharField(
                choices=[
                    ("creality_cfs", "Creality CFS"),
                    ("simplyprint", "SimplyPrint"),
                    ("bambu_ams", "Bambu Lab AMS"),
                    ("elegoo", "Elegoo multi-material"),
                    ("qidi", "QIDI multi-material"),
                    ("snapmaker", "Snapmaker multi-material"),
                    ("generic", "Generic / other"),
                ],
                default="generic",
                max_length=30,
            ),
        ),
    ]
