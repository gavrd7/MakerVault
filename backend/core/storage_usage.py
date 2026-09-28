from __future__ import annotations

from dataclasses import dataclass

from django.db import transaction

from .models import FileAsset, InventoryItem, Project, StorageSettings, UserStorageProfile


GIB = 1024 * 1024 * 1024


@dataclass(frozen=True)
class StorageUsage:
    models_bytes: int = 0
    project_files_bytes: int = 0
    images_bytes: int = 0
    other_files_bytes: int = 0

    @property
    def total_bytes(self) -> int:
        return (
            self.models_bytes
            + self.project_files_bytes
            + self.images_bytes
            + self.other_files_bytes
        )


def _field_size(field) -> int:
    if not field:
        return 0
    try:
        return max(int(field.size or 0), 0)
    except (FileNotFoundError, OSError, ValueError, TypeError):
        return 0


def _asset_size(asset: FileAsset) -> int:
    metadata = asset.metadata or {}
    try:
        stored = int(metadata.get("size_bytes") or 0)
    except (TypeError, ValueError):
        stored = 0
    return max(stored, _field_size(asset.file))


def calculate_user_storage(user) -> StorageUsage:
    models_bytes = project_files_bytes = images_bytes = other_files_bytes = 0

    assets = FileAsset.objects.filter(owner=user)
    for asset in assets.iterator():
        size = _asset_size(asset)
        if asset.category == "image":
            images_bytes += size
        elif asset.model_revisions.exists() or asset.category in {"mesh", "slicer", "cad"}:
            models_bytes += size
        elif asset.project_id:
            project_files_bytes += size
        else:
            other_files_bytes += size

    for project in Project.objects.filter(owner=user).only("cover_image").iterator():
        images_bytes += _field_size(project.cover_image)

    for item in InventoryItem.objects.filter(owner=user).only("image").iterator():
        images_bytes += _field_size(item.image)

    return StorageUsage(
        models_bytes=models_bytes,
        project_files_bytes=project_files_bytes,
        images_bytes=images_bytes,
        other_files_bytes=other_files_bytes,
    )


def storage_settings() -> StorageSettings:
    settings, _ = StorageSettings.objects.get_or_create(singleton_key=1)
    return settings


@transaction.atomic
def refresh_user_storage_profile(user) -> UserStorageProfile:
    profile, _ = UserStorageProfile.objects.select_for_update().get_or_create(user=user)
    usage = calculate_user_storage(user)
    profile.storage_used_bytes = usage.total_bytes
    profile.models_bytes = usage.models_bytes
    profile.project_files_bytes = usage.project_files_bytes
    profile.images_bytes = usage.images_bytes
    profile.other_files_bytes = usage.other_files_bytes
    profile.save(update_fields=[
        "storage_used_bytes",
        "models_bytes",
        "project_files_bytes",
        "images_bytes",
        "other_files_bytes",
        "updated_at",
    ])
    return profile


def effective_quota_bytes(profile: UserStorageProfile) -> int | None:
    if profile.quota_unlimited:
        return None
    if profile.quota_override_bytes is not None:
        return int(profile.quota_override_bytes)
    return int(storage_settings().default_quota_bytes)


def storage_summary(user, *, refresh: bool = True) -> dict:
    profile = refresh_user_storage_profile(user) if refresh else UserStorageProfile.objects.get_or_create(user=user)[0]
    quota = effective_quota_bytes(profile)
    used = int(profile.storage_used_bytes)
    percent = None
    if quota is not None:
        percent = 100.0 if quota == 0 and used else (0.0 if quota == 0 else round((used / quota) * 100, 1))
    return {
        "used_bytes": used,
        "quota_bytes": quota,
        "unlimited": quota is None,
        "percent_used": percent,
        "remaining_bytes": None if quota is None else max(quota - used, 0),
        "categories": {
            "models": int(profile.models_bytes),
            "project_files": int(profile.project_files_bytes),
            "images": int(profile.images_bytes),
            "other_files": int(profile.other_files_bytes),
        },
    }
