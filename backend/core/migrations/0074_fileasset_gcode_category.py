from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0073_device_makertag_operation"),
    ]

    operations = [
        migrations.AlterField(
            model_name="fileasset",
            name="category",
            field=models.CharField(
                choices=[
                    ("image", "Image"),
                    ("wiring", "Wiring / schematic"),
                    ("firmware", "Firmware"),
                    ("source", "Source code"),
                    ("binary", "Executable / binary"),
                    ("document", "Document"),
                    ("cad", "CAD"),
                    ("mesh", "STL / mesh"),
                    ("slicer", "3MF / slicer project"),
                    ("gcode", "G-code"),
                    ("pcb", "PCB"),
                    ("archive", "Archive"),
                    ("other", "Other"),
                ],
                default="other",
                max_length=20,
            ),
        ),
    ]
