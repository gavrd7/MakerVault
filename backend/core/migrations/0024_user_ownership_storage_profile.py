import os

from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


PRIVATE_MODELS = (
    "Project",
    "InventoryItem",
    "FileAsset",
    "PrintingLocation",
    "PrintingIntegrationSetting",
    "Spool",
    "Printer",
    "Model3D",
    "PrintJob",
)


def _legacy_owner(apps):
    User = apps.get_model(*settings.AUTH_USER_MODEL.split("."))
    username = os.getenv("MAKERVAULT_LEGACY_OWNER_USERNAME", "").strip()
    if username:
        try:
            return User.objects.get(username=username)
        except User.DoesNotExist as exc:
            raise RuntimeError(
                "MAKERVAULT_LEGACY_OWNER_USERNAME names a user that does not exist. "
                "Correct the setting before retrying the migration."
            ) from exc

    users = list(User.objects.all().order_by("pk")[:3])
    if len(users) == 1:
        return users[0]

    superusers = list(User.objects.filter(is_superuser=True).order_by("pk")[:3])
    if len(superusers) == 1:
        return superusers[0]

    return None


def assign_legacy_ownership(apps, schema_editor):
    Project = apps.get_model("core", "Project")
    InventoryItem = apps.get_model("core", "InventoryItem")
    FileAsset = apps.get_model("core", "FileAsset")
    PrintingLocation = apps.get_model("core", "PrintingLocation")
    PrintingIntegrationSetting = apps.get_model("core", "PrintingIntegrationSetting")
    Spool = apps.get_model("core", "Spool")
    Printer = apps.get_model("core", "Printer")
    Model3D = apps.get_model("core", "Model3D")
    PrintJob = apps.get_model("core", "PrintJob")

    # Projects already record their creator, so preserve that attribution first.
    for project in Project.objects.filter(owner__isnull=True, created_by__isnull=False).iterator():
        project.owner_id = project.created_by_id
        project.save(update_fields=["owner"])

    owner = _legacy_owner(apps)

    # Relationship-based attribution is safe even when an installation already has
    # multiple users. Anything genuinely ambiguous falls back to the explicit/sole owner.
    for item in InventoryItem.objects.filter(owner__isnull=True, project__owner__isnull=False).iterator():
        item.owner_id = item.project.owner_id
        item.save(update_fields=["owner"])

    for asset in FileAsset.objects.filter(owner__isnull=True, project__owner__isnull=False).iterator():
        asset.owner_id = asset.project.owner_id
        asset.save(update_fields=["owner"])

    for model in Model3D.objects.filter(owner__isnull=True, project__owner__isnull=False).iterator():
        model.owner_id = model.project.owner_id
        model.save(update_fields=["owner"])

    for job in PrintJob.objects.filter(owner__isnull=True, project__owner__isnull=False).iterator():
        job.owner_id = job.project.owner_id
        job.save(update_fields=["owner"])
    for job in PrintJob.objects.filter(owner__isnull=True, printer__owner__isnull=False).iterator():
        job.owner_id = job.printer.owner_id
        job.save(update_fields=["owner"])
    for job in PrintJob.objects.filter(
        owner__isnull=True,
        model_revision__model__owner__isnull=False,
    ).iterator():
        job.owner_id = job.model_revision.model.owner_id
        job.save(update_fields=["owner"])

    unresolved = []
    model_map = {
        "Project": Project,
        "InventoryItem": InventoryItem,
        "FileAsset": FileAsset,
        "PrintingLocation": PrintingLocation,
        "PrintingIntegrationSetting": PrintingIntegrationSetting,
        "Spool": Spool,
        "Printer": Printer,
        "Model3D": Model3D,
        "PrintJob": PrintJob,
    }
    for name, Model in model_map.items():
        count = Model.objects.filter(owner__isnull=True).count()
        if count:
            unresolved.append((name, count))

    if unresolved and owner is None:
        details = ", ".join(f"{name}={count}" for name, count in unresolved)
        raise RuntimeError(
            "MakerVault cannot safely determine who owns existing private data "
            f"({details}). Set MAKERVAULT_LEGACY_OWNER_USERNAME to the account that "
            "should receive legacy unowned records, then restart the container."
        )

    if owner is not None:
        for Model in model_map.values():
            Model.objects.filter(owner__isnull=True).update(owner_id=owner.pk)

        Profile = apps.get_model("core", "UserStorageProfile")
        Profile.objects.get_or_create(user_id=owner.pk)


def reverse_legacy_ownership(apps, schema_editor):
    for name in PRIVATE_MODELS:
        apps.get_model("core", name).objects.update(owner=None)


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0023_fileasset_version_lineage"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="UserStorageProfile",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("quota_override_bytes", models.BigIntegerField(blank=True, null=True)),
                ("storage_used_bytes", models.BigIntegerField(default=0)),
                ("models_bytes", models.BigIntegerField(default=0)),
                ("project_files_bytes", models.BigIntegerField(default=0)),
                ("images_bytes", models.BigIntegerField(default=0)),
                ("other_files_bytes", models.BigIntegerField(default=0)),
                ("user", models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name="makervault_storage_profile", to=settings.AUTH_USER_MODEL)),
            ],
            options={"ordering": ["user__username"]},
        ),
        *[
            migrations.AddField(
                model_name=model_name,
                name="owner",
                field=models.ForeignKey(
                    blank=True,
                    null=True,
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name=related_name,
                    to=settings.AUTH_USER_MODEL,
                ),
            )
            for model_name, related_name in [
                ("project", "owned_makervault_projects"),
                ("inventoryitem", "makervault_inventory_items"),
                ("fileasset", "makervault_file_assets"),
                ("printinglocation", "makervault_printing_locations"),
                ("printingintegrationsetting", "makervault_printing_integrations"),
                ("spool", "makervault_spools"),
                ("printer", "makervault_printers"),
                ("model3d", "makervault_models_3d"),
                ("printjob", "makervault_print_jobs"),
            ]
        ],
        migrations.RunPython(assign_legacy_ownership, reverse_legacy_ownership),
    ]
