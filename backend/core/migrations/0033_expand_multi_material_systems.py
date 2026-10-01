# Generated for MakerVault v0.7.3 manufacturer adapter expansion.

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0032_printer_connections"),
    ]

    operations = [
        migrations.AlterField(
            model_name="printercatalogmodel",
            name="multi_material_system",
            field=models.CharField(
                blank=True,
                choices=[
                    ("", "None / unknown"),
                    ("creality_cfs", "Creality CFS"),
                    ("bambu_ams", "Bambu Lab AMS"),
                    ("anycubic_ace", "Anycubic ACE / ACE Pro"),
                    ("flashforge_station", "FlashForge material station"),
                    ("prusa_mmu", "Prusa MMU"),
                    ("elegoo", "Elegoo multi-material"),
                    ("qidi", "QIDI multi-material"),
                    ("sovol", "Sovol multi-material / toolchanger"),
                    ("snapmaker", "Snapmaker multi-material"),
                    ("voron", "Voron community multi-material / toolchanger"),
                    ("other", "Other"),
                ],
                max_length=30,
            ),
        ),
        migrations.AlterField(
            model_name="printerfilamentslot",
            name="system",
            field=models.CharField(
                choices=[
                    ("creality_cfs", "Creality CFS"),
                    ("simplyprint", "SimplyPrint"),
                    ("bambu_ams", "Bambu Lab AMS"),
                    ("anycubic_ace", "Anycubic ACE / ACE Pro"),
                    ("flashforge_station", "FlashForge material station"),
                    ("prusa_mmu", "Prusa MMU"),
                    ("elegoo", "Elegoo multi-material"),
                    ("qidi", "QIDI multi-material"),
                    ("sovol", "Sovol multi-material / toolchanger"),
                    ("snapmaker", "Snapmaker multi-material"),
                    ("voron", "Voron community multi-material / toolchanger"),
                    ("generic", "Generic / other"),
                ],
                default="generic",
                max_length=30,
            ),
        ),
    ]
