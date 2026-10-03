from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0035_printed_parts"),
    ]

    operations = [
        migrations.AlterField(
            model_name="printingintegrationsetting",
            name="provider",
            field=models.CharField(
                choices=[
                    ("spoolman", "Spoolman"),
                    ("simplyprint", "SimplyPrint"),
                    ("creality_cfs", "Creality CFS"),
                    ("bambu_ams", "Bambu Lab / AMS"),
                    ("prusalink", "PrusaLink"),
                    ("anycubic_ace", "Anycubic LAN / ACE"),
                    ("flashforge_station", "FlashForge local / material station"),
                    ("elegoo", "Elegoo / Moonraker"),
                    ("qidi", "QIDI / Moonraker"),
                    ("sovol", "Sovol / Moonraker"),
                    ("snapmaker", "Snapmaker U1 / Moonraker"),
                    ("voron", "Voron / Moonraker"),
                ],
                max_length=30,
            ),
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
                    ("experimental", "Experimental"),
                    ("planned", "Planned"),
                ],
                default="not_configured",
                max_length=24,
            ),
        ),
    ]
