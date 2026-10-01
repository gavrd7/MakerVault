# Generated for MakerVault v0.7.3 live printer connectivity.

import django.db.models.deletion
import uuid
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0031_standalone_wiring"),
    ]

    operations = [
        migrations.CreateModel(
            name="PrinterConnection",
            fields=[
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("adapter", models.CharField(choices=[
                    ("moonraker", "Moonraker / Klipper"),
                    ("octoprint", "OctoPrint"),
                    ("creality_local", "Creality local"),
                    ("simplyprint", "SimplyPrint"),
                    ("bambu_local", "Bambu Lab local"),
                    ("anycubic", "Anycubic"),
                    ("flashforge", "FlashForge"),
                    ("prusa", "Prusa"),
                    ("elegoo", "Elegoo"),
                    ("qidi", "QIDI"),
                    ("sovol", "Sovol"),
                    ("snapmaker", "Snapmaker"),
                    ("voron", "Voron"),
                    ("other", "Other / custom"),
                ], max_length=40)),
                ("enabled", models.BooleanField(default=True)),
                ("endpoint_url", models.CharField(blank=True, max_length=500)),
                ("poll_interval_seconds", models.PositiveSmallIntegerField(default=30)),
                ("status", models.CharField(choices=[
                    ("not_configured", "Not configured"),
                    ("disabled", "Disabled"),
                    ("connecting", "Connecting"),
                    ("connected", "Connected"),
                    ("disconnected", "Disconnected"),
                    ("error", "Error"),
                    ("experimental", "Experimental"),
                ], default="not_configured", max_length=24)),
                ("capabilities", models.JSONField(blank=True, default=dict)),
                ("last_snapshot", models.JSONField(blank=True, default=dict)),
                ("last_checked_at", models.DateTimeField(blank=True, null=True)),
                ("last_seen_at", models.DateTimeField(blank=True, null=True)),
                ("last_error", models.TextField(blank=True)),
                ("config", models.JSONField(blank=True, default=dict)),
                ("printer", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="live_connections", to="core.printer")),
            ],
            options={
                "ordering": ["printer__name", "adapter"],
            },
        ),
        migrations.AddConstraint(
            model_name="printerconnection",
            constraint=models.UniqueConstraint(fields=("printer", "adapter"), name="unique_printer_live_adapter"),
        ),
    ]
