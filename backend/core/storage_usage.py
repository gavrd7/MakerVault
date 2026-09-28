from __future__ import annotations

from dataclasses import dataclass

from django.db import transaction

from .models import FileAsset, InventoryItem, Project, StorageSettings, UserStorageProfile


GIB = 1024 * 1024 * 1024


class StorageQuotaExceeded(Exception):
    """Raised before a write would grow a user's persistent storage beyond quota."""

    def __init__(self, *, used_bytes: int, quota_bytes: int, requested_bytes: int, projected_bytes: int):
        super().__init__("Storage quota exceeded.")
        self.used_bytes = used_bytes
        self.quota_bytes = quota_bytes
        self.requested_bytes = requested_bytes
        self.projected_bytes = projected_bytes


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


def ensure_storage_capacity(user, incoming_bytes: int, *, replacing_bytes: int = 0) -> int:
    """Reject a persistent write before it grows storage beyond the effective quota.

    Returns the logical growth in bytes. Replacement writes are charged only for
    positive net growth, while immutable revisions always pass replacing_bytes=0.
    The usage profile is refreshed from real stored files before every decision so
    stale cached counters cannot be used to bypass quota enforcement.
    """
    try:
        incoming = max(int(incoming_bytes or 0), 0)
    except (TypeError, ValueError):
        incoming = 0
    try:
        replacing = max(int(replacing_bytes or 0), 0)
    except (TypeError, ValueError):
        replacing = 0

    growth = max(incoming - replacing, 0)
    profile = refresh_user_storage_profile(user)
    quota = effective_quota_bytes(profile)
    used = int(profile.storage_used_bytes)
    projected = used + growth
    if quota is not None and projected > quota:
        raise StorageQuotaExceeded(
            used_bytes=used,
            quota_bytes=int(quota),
            requested_bytes=growth,
            projected_bytes=projected,
        )
    return growth


def _warning_level(used: int, quota: int | None) -> str:
    if quota is None:
        return "unlimited"
    if quota <= 0 or used >= quota:
        return "full"
    ratio = used / quota
    if ratio >= 0.90:
        return "critical"
    if ratio >= 0.80:
        return "warning"
    return "ok"


def storage_summary(user, *, refresh: bool = True) -> dict:
    profile = refresh_user_storage_profile(user) if refresh else UserStorageProfile.objects.get_or_create(user=user)[0]
    quota = effective_quota_bytes(profile)
    used = int(profile.storage_used_bytes)
    percent = None
    if quota is not None:
        percent = 100.0 if quota == 0 else round((used / quota) * 100, 1)
    return {
        "used_bytes": used,
        "quota_bytes": quota,
        "unlimited": quota is None,
        "percent_used": percent,
        "remaining_bytes": None if quota is None else max(quota - used, 0),
        "warning_level": _warning_level(used, quota),
        "can_upload": quota is None or used < quota,
        "categories": {
            "models": int(profile.models_bytes),
            "project_files": int(profile.project_files_bytes),
            "images": int(profile.images_bytes),
            "other_files": int(profile.other_files_bytes),
        },
    }
