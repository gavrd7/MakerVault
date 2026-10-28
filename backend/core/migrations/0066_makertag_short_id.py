from django.db import migrations, models
import secrets


def backfill_short_ids(apps, schema_editor):
    Tag = apps.get_model("core", "MakerTag")
    db = schema_editor.connection.alias
    allocated = set(Tag.objects.using(db).exclude(short_id__isnull=True).values_list("short_id", flat=True))
    for tag in Tag.objects.using(db).filter(short_id__isnull=True).only("id", "public_token").iterator():
        # Prefer the existing public-token prefix for familiar visible IDs,
        # but never accept a collision.
        candidate = tag.public_token.hex[:8].upper()
        while candidate in allocated:
            candidate = secrets.token_hex(4).upper()
        Tag.objects.using(db).filter(pk=tag.pk).update(short_id=candidate)
        allocated.add(candidate)


class Migration(migrations.Migration):
    dependencies = [("core", "0065_devicetaglookup")]

    operations = [
        migrations.AddField(
            model_name="makertag",
            name="short_id",
            field=models.CharField(blank=True, editable=False, max_length=8, null=True, unique=True),
        ),
        migrations.RunPython(backfill_short_ids, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="makertag",
            name="short_id",
            field=models.CharField(editable=False, max_length=8, unique=True),
        ),
    ]
