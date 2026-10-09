from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("core", "0039_project_priority_due_date")]

    operations = [
        migrations.AddField(
            model_name="cataloguemaintenancesettings",
            name="board_enrichment_cursor",
            field=models.CharField(blank=True, default="", max_length=64),
        ),
    ]
