import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("core", "0057_reusable_spool_suggestions")]
    operations = [
        migrations.AddField(
            model_name="reusablespoolcataloguesuggestion",
            name="target_entry",
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name="correction_suggestions", to="core.reusablespoolcatalogentry"),
        ),
    ]
