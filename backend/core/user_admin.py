from __future__ import annotations

from django.db import transaction

from .models import (
    FileAsset,
    InventoryItem,
    Model3D,
    PrintJob,
    Printer,
    PrintingIntegrationSetting,
    PrintingLocation,
    Project,
    Spool,
    UserStorageProfile,
)
from .storage_usage import refresh_user_storage_profile, storage_summary


def admin_user_summary(user) -> dict:
    """Return account/storage metadata only; never private record names or paths."""
    profile, _ = UserStorageProfile.objects.get_or_create(user=user)
    storage = storage_summary(user)
    if profile.quota_unlimited:
        quota_mode = "unlimited"
    elif profile.quota_override_bytes is not None:
        quota_mode = "override"
    else:
        quota_mode = "default"

    return {
        "id": user.pk,
        "username": user.get_username(),
        "email": user.email or "",
        "is_active": bool(user.is_active),
        "is_staff": bool(user.is_staff),
        "is_superuser": bool(user.is_superuser),
        "date_joined": user.date_joined.isoformat() if user.date_joined else None,
        "last_login": user.last_login.isoformat() if user.last_login else None,
        "quota_mode": quota_mode,
        "quota_override_bytes": profile.quota_override_bytes,
        "storage": storage,
        "counts": {
            "projects": Project.objects.filter(owner=user).count(),
            "inventory": InventoryItem.objects.filter(owner=user).count(),
            "files": FileAsset.objects.filter(owner=user).count(),
            "printers": Printer.objects.filter(owner=user).count(),
            "spools": Spool.objects.filter(owner=user).count(),
            "models": Model3D.objects.filter(owner=user).count(),
            "print_jobs": PrintJob.objects.filter(owner=user).count(),
            "integrations": PrintingIntegrationSetting.objects.filter(owner=user).count(),
        },
    }


def _delete_field_file(field) -> None:
    if not field:
        return
    try:
        field.delete(save=False)
    except (FileNotFoundError, OSError, ValueError):
        pass


def delete_user_file_blobs(user) -> None:
    """Delete physical private blobs without exposing their names to an administrator."""
    for asset in FileAsset.objects.filter(owner=user).only("file").iterator():
        _delete_field_file(asset.file)
    for project in Project.objects.filter(owner=user).only("cover_image").iterator():
        _delete_field_file(project.cover_image)
    for item in InventoryItem.objects.filter(owner=user).only("image").iterator():
        _delete_field_file(item.image)


@transaction.atomic
def purge_user_private_data(user) -> dict:
    """Remove a user's MakerVault-private workspace while preserving the account."""
    before = admin_user_summary(user)
    delete_user_file_blobs(user)

    # Delete dependants before protected parents. Shared catalogue/reference data is untouched.
    PrintJob.objects.filter(owner=user).delete()
    Model3D.objects.filter(owner=user).delete()
    FileAsset.objects.filter(owner=user).delete()
    Project.objects.filter(owner=user).delete()
    InventoryItem.objects.filter(owner=user).delete()
    Spool.objects.filter(owner=user).delete()
    Printer.objects.filter(owner=user).delete()
    PrintingLocation.objects.filter(owner=user).delete()
    PrintingIntegrationSetting.objects.filter(owner=user).delete()

    refresh_user_storage_profile(user)
    return {
        "storage_bytes_removed": int(before["storage"]["used_bytes"]),
        "counts_removed": before["counts"],
    }
