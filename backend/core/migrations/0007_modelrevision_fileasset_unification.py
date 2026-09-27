from pathlib import Path

from django.db import migrations


def migrate_legacy_revision_files(apps, schema_editor):
    ModelRevision = apps.get_model("core", "ModelRevision")
    FileAsset = apps.get_model("core", "FileAsset")
    ModelRevisionAsset = apps.get_model("core", "ModelRevisionAsset")

    field_map = [
        ("stl_file", "mesh", "model", "STL"),
        ("three_mf_file", "slicer", "slicer", "3MF"),
        ("cad_file", "cad", "cad", "CAD"),
    ]

    for revision in ModelRevision.objects.select_related("model").all().iterator():
        for field_name, category, role, label in field_map:
            field = getattr(revision, field_name, None)
            file_name = getattr(field, "name", "") if field else ""
            if not file_name:
                continue

            original_name = Path(file_name).name
            asset = FileAsset.objects.create(
                project_id=revision.model.project_id,
                name=f"{revision.model.name} {revision.version} {label}"[:255],
                category=category,
                file=file_name,
                version=revision.version[:80],
                description=f"Migrated from legacy ModelRevision.{field_name}",
                metadata={
                    "original_name": original_name,
                    "extension": Path(original_name).suffix.lower(),
                    "migrated_from": f"ModelRevision.{field_name}",
                },
            )
            ModelRevisionAsset.objects.get_or_create(
                revision_id=revision.pk,
                file_asset_id=asset.pk,
                defaults={
                    "role": role,
                    "is_primary": True,
                    "notes": "Migrated from legacy direct revision file field.",
                },
            )


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0006_printing_foundation"),
    ]

    operations = [
        migrations.RunPython(migrate_legacy_revision_files, migrations.RunPython.noop),
        migrations.RemoveField(model_name="modelrevision", name="stl_file"),
        migrations.RemoveField(model_name="modelrevision", name="three_mf_file"),
        migrations.RemoveField(model_name="modelrevision", name="cad_file"),
    ]
