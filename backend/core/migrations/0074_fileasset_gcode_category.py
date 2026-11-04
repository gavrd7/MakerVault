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
        migrations.AlterField(
            model_name="modelrevisionasset",
            name="role",
            field=models.CharField(
                choices=[
                    ("model", "Printable model"),
                    ("slicer", "Slicer project"),
                    ("gcode", "G-code toolpath"),
                    ("cad", "CAD / source"),
                    ("reference", "Reference"),
                    ("other", "Other"),
                ],
                default="model",
                max_length=20,
            ),
        ),
    ]
