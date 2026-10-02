from __future__ import annotations

import json
from pathlib import Path

from django.conf import settings
from django.http import HttpResponse, JsonResponse

from .backup_bundle import (
    BackupBundleError,
    SAFE_ID,
    backup_root,
    bundle_path,
    maintenance_lock_path,
    metadata_path,
    prepare_backup,
    read_metadata_file,
    release_lock,
    validate_backup_id,
    mark_failed,
)


class BackupServiceError(RuntimeError):
    pass


def managed_backup_capability() -> tuple[bool, str]:
    database = settings.DATABASES.get("default", {})
    host = str(database.get("HOST") or "").strip()
    port = str(database.get("PORT") or "5432").strip()
    if host not in {"postgres", "makervault-postgres"} or port not in {"", "5432"}:
        return False, (
            "Managed backups require MakerVault's supplied local PostgreSQL service. "
            "Use the advanced backup procedure for an external database."
        )

    if not settings.MAKERVAULT_STORAGE_KEY:
        key_path = settings.MAKERVAULT_STORAGE_KEY_FILE
        if not key_path:
            return False, "MakerVault has no configured private-storage key source."
        try:
            Path(key_path).resolve().relative_to(Path("/app/keys"))
        except ValueError:
            return False, (
                "Managed backups require the private-storage key to be inline in .env "
                "or stored under /app/keys. Use the advanced procedure for a custom key mount."
            )

    return True, ""


def backup_in_progress() -> bool:
    return maintenance_lock_path().is_file()


def _safe_id(value: str) -> str:
    value = str(value or "")
    if not SAFE_ID.fullmatch(value):
        raise BackupServiceError("Invalid backup identifier.")
    return value


def read_metadata(path: Path) -> dict | None:
    data = read_metadata_file(path)
    if not data:
        return None
    bundle = bundle_path(data["id"])
    if data.get("status") == "running" and not backup_in_progress():
        data["status"] = "interrupted"
        data["verified"] = False
        data["error"] = data.get("error") or (
            "Backup stopped before completion. It is not a usable recovery bundle."
        )
    data["download_available"] = bundle.is_file() and data.get("status") == "complete"
    data["restore_command"] = (
        f"python3 scripts/restore.py --sudo --backup-id {data['id']}"
        if data["download_available"]
        else ""
    )
    return data


def list_backups() -> list[dict]:
    rows = []
    for path in backup_root().glob("*.json"):
        item = read_metadata(path)
        if item:
            rows.append(item)
    rows.sort(key=lambda item: str(item.get("created_at") or ""), reverse=True)
    return rows


def get_backup(backup_id: str) -> dict:
    path = metadata_path(_safe_id(backup_id))
    item = read_metadata(path) if path.is_file() else None
    if not item:
        raise BackupServiceError("Backup not found.")
    return item


def delete_backup(backup_id: str):
    backup_id = _safe_id(backup_id)
    item = get_backup(backup_id)
    if item.get("status") == "running" or backup_in_progress():
        raise BackupServiceError("A backup is currently running.")
    bundle_path(backup_id).unlink(missing_ok=True)
    metadata_path(backup_id).unlink(missing_ok=True)


def create_backup() -> dict:
    try:
        item = prepare_backup(label="MakerVault UI")
    except BackupBundleError as exc:
        raise BackupServiceError(str(exc)) from exc

    backup_id = item["id"]
    try:
        from .tasks import create_managed_backup_task

        create_managed_backup_task.delay(backup_id)
    except Exception as exc:
        mark_failed(backup_id, f"Could not queue backup task: {exc}")
        release_lock(backup_id)
        raise BackupServiceError("MakerVault could not queue the backup job.") from exc

    return {"backup_id": backup_id, "status": "starting"}


def validate_backup(backup_id: str) -> dict:
    backup_id = _safe_id(backup_id)
    try:
        return validate_backup_id(backup_id)
    except BackupBundleError as exc:
        raise BackupServiceError(str(exc)) from exc


class BackupMaintenanceMiddleware:
    """Make the normal web UI read-only while a consistent backup is captured."""

    SAFE_METHODS = {"GET", "HEAD", "OPTIONS", "TRACE"}

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.method not in self.SAFE_METHODS and backup_in_progress():
            message = (
                "MakerVault is briefly read-only while a backup is being created. "
                "Try again when the backup finishes."
            )
            if request.path.startswith("/api/"):
                return JsonResponse(
                    {"error": message, "code": "backup_in_progress"},
                    status=503,
                )
            return HttpResponse(
                message,
                status=503,
                content_type="text/plain; charset=utf-8",
            )
        return self.get_response(request)
