from __future__ import annotations

from django.db import transaction
from django.contrib.auth.models import Group

from .models import (
    FileAsset,
    InventoryItem,
    Model3D,
    PrintJob,
    PrintedPart,
    Printer,
    PrintingIntegrationSetting,
    PrintingLocation,
    Project,
    Spool,
    UserStorageProfile,
)
from .storage_usage import refresh_user_storage_profile, storage_summary


ROLE_GROUPS = ("Supervisor", "User", "Editor", "Viewer")


def user_role(user):
    if user.is_superuser:
        return "Admin"
    groups = set(user.groups.values_list("name", flat=True))
    for name in ROLE_GROUPS:
        if name in groups:
            return name
    return "Staff" if user.is_staff else "User"


def can_manage_workspace_settings(user):
    return bool(user.is_superuser or user.is_staff or user.groups.filter(name="Supervisor").exists())


def assign_user_role(target, role):
    if role not in {"Admin", "Supervisor", "User", "Viewer"}:
        raise ValueError("Unknown account role.")
    role_group_names = ("Supervisor", "User", "Editor", "Viewer")
    # Only superusers may administer the instance or grant roles.
    target.is_superuser = role == "Admin"
    target.is_staff = role == "Admin"
    with transaction.atomic():
        target.save(update_fields=["is_superuser", "is_staff"])
        groups = Group.objects.filter(name__in=role_group_names)
        target.groups.remove(*groups)
        if role != "Admin":
            group = Group.objects.get(name=role)
            target.groups.add(group)


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
        "role": user_role(user),
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
            "printed_parts": PrintedPart.objects.filter(owner=user).count(),
            "integrations": PrintingIntegrationSetting.objects.filter(owner=user).count(),
        },
    }


def _private_blob_refs(user):
    """Capture storage/name pairs without returning private names to the API caller."""
    refs = []
    for field in FileAsset.objects.filter(owner=user).only("file").values_list("file", flat=True):
        if field:
            refs.append((FileAsset._meta.get_field("file").storage, str(field)))
    for field in Project.objects.filter(owner=user).only("cover_image").values_list("cover_image", flat=True):
        if field:
            refs.append((Project._meta.get_field("cover_image").storage, str(field)))
    for field in InventoryItem.objects.filter(owner=user).only("image").values_list("image", flat=True):
        if field:
            refs.append((InventoryItem._meta.get_field("image").storage, str(field)))
    return refs


def _delete_blob_refs(refs) -> None:
    for storage, name in refs:
        try:
            storage.delete(name)
        except (FileNotFoundError, OSError, ValueError):
            # A stale/orphaned blob is not exposed by the private media view and
            # can be cleaned later; DB integrity takes priority over disk cleanup.
            pass


def purge_user_private_data(user) -> dict:
    """Remove a user's MakerVault-private workspace while preserving the account."""
    before = admin_user_summary(user)
    blob_refs = _private_blob_refs(user)

    # Commit database deletion before touching physical blobs. If a protected
    # relation or another database constraint fails, all live file records remain
    # intact and their blobs are not removed.
    with transaction.atomic():
        PrintedPart.objects.filter(owner=user).delete()
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

    _delete_blob_refs(blob_refs)
    return {
        "storage_bytes_removed": int(before["storage"]["used_bytes"]),
        "counts_removed": before["counts"],
    }

