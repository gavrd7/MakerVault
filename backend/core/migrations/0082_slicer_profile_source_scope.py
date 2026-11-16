from django.db import migrations, models


def backfill_official_scope(apps, schema_editor):
    """Keep existing native files and profile IDs while preserving their origin.

    Only provenance from pinned official imports is eligible. Hand-imported
    profiles retain the empty/manual namespace.
    """
    Profile = apps.get_model("core", "SlicerProfile")
    known_sources = (
        "OrcaSlicer/OrcaSlicer@", "CrealityOfficial/CrealityPrint@",
        "Snapmaker/OrcaSlicer@", "bambulab/BambuStudio@",
    )
    for profile in Profile.objects.exclude(provenance="").iterator():
        label = profile.provenance
        if not label.startswith(known_sources) or "@" not in label:
            continue
        source, separator, remainder = label.partition("@")
        parts = remainder.split("/", 2)
        if separator and len(parts) == 3 and all(parts[:2]):
            scope = source + "@" + parts[0] + "/" + parts[1]
            Profile.objects.filter(pk=profile.pk).update(source_scope=scope[:200])


class Migration(migrations.Migration):
    dependencies = [("core", "0081_home_assistant_printer_power_provider")]

    operations = [
        migrations.AddField(
            model_name="slicerprofile",
            name="source_scope",
            field=models.CharField(max_length=200, blank=True, default="", db_index=True),
        ),
        migrations.RunPython(backfill_official_scope, migrations.RunPython.noop),
        migrations.RemoveConstraint(
            model_name="slicerprofile", name="unique_slicer_profile_identity",
        ),
        migrations.AddConstraint(
            model_name="slicerprofile",
            constraint=models.UniqueConstraint(
                fields=["owner", "engine", "engine_version", "kind", "name", "source_scope"],
                name="unique_slicer_profile_identity",
            ),
        ),
    ]
