from django.db import migrations, models



def normalise_live_integration_statuses(apps, schema_editor):
    Integration = apps.get_model("core", "PrintingIntegrationSetting")
    Integration.objects.filter(
        provider__in=["spoolman", "creality_cfs"],
        enabled=False,
    ).update(status="disabled")
    Integration.objects.filter(
        provider="creality_cfs",
        enabled=True,
        status="ready",
    ).update(status="disconnected")


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0011_printing_catalogues_locations_integrations"),
    ]

    operations = [
        migrations.AddField(
            model_name="printingintegrationsetting",
            name="auto_sync",
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name="printingintegrationsetting",
            name="last_sync_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="printingintegrationsetting",
            name="last_sync_result",
            field=models.JSONField(blank=True, default=dict),
        ),
        migrations.AddField(
            model_name="printingintegrationsetting",
            name="last_sync_triggered_by",
            field=models.CharField(blank=True, max_length=120),
        ),
        migrations.AddField(
            model_name="printingintegrationsetting",
            name="next_sync_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="printingintegrationsetting",
            name="sync_interval_minutes",
            field=models.PositiveIntegerField(default=15),
        ),
        migrations.AlterField(
            model_name="printingintegrationsetting",
            name="status",
            field=models.CharField(
                choices=[
                    ("disabled", "Disabled"),
                    ("not_configured", "Not configured"),
                    ("ready", "Ready"),
                    ("connected", "Connected"),
                    ("disconnected", "Disconnected"),
                    ("error", "Error"),
                    ("planned", "Planned"),
                ],
                default="not_configured",
                max_length=24,
            ),
        ),
        migrations.RunPython(normalise_live_integration_statuses, migrations.RunPython.noop),
    ]
