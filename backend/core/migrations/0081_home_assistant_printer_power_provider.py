from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("core", "0080_slicer_profile_defaults")]

    operations = [
        migrations.AlterField(
            model_name="printingintegrationsetting",
            name="provider",
            field=models.CharField(max_length=30, choices=[
                ("spoolman", "Spoolman"),
                ("simplyprint", "SimplyPrint"),
                ("creality_cfs", "Creality CFS"),
                ("homeassistant", "Home Assistant · printer power"),
                ("bambu_ams", "Bambu Lab / AMS"),
                ("prusalink", "PrusaLink"),
                ("anycubic_ace", "Anycubic LAN / ACE"),
                ("flashforge_station", "FlashForge local / material station"),
                ("elegoo", "Elegoo / Moonraker"),
                ("qidi", "QIDI / Moonraker"),
                ("sovol", "Sovol / Moonraker"),
                ("snapmaker", "Snapmaker U1 / Moonraker"),
                ("voron", "Voron / Moonraker"),
            ]),
        ),
    ]
