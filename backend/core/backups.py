from __future__ import annotations

import json
from pathlib import Path
import re
import urllib.error
import urllib.parse
import urllib.request

from django.conf import settings
from django.http import HttpResponse, JsonResponse


SAFE_ID = re.compile(r"^[A-Za-z0-9_-]+$")


class BackupServiceError(RuntimeError):
    pass


def managed_backup_capability() -> tuple[bool, str]:
    database = settings.DATABASES.get("default", {})
    host = str(database.get("HOST") or "").strip()
    port = str(database.get("PORT") or "5432").strip()
    if host not in {"postgres", "makervault-postgres"} or port not in {"", "5432"}:
        return False, "Managed backups require MakerVault's supplied local PostgreSQL service. Use the advanced backup procedure for an external database."

    if not settings.MAKERVAULT_STORAGE_KEY:
        key_path = settings.MAKERVAULT_STORAGE_KEY_FILE
        if not key_path:
            return False, "MakerVault has no configured private-storage key source."
        try:
            Path(key_path).resolve().relative_to(Path("/app/keys"))
        except ValueError:
            return False, "Managed backups require the private-storage key to be inline in .env or stored under /app/keys. Use the advanced procedure for a custom key mount."

    return True, ""


def backup_root() -> Path:
    root = Path(settings.MAKERVAULT_BACKUP_ROOT)
    root.mkdir(parents=True, exist_ok=True)
    return root


def maintenance_lock_path() -> Path:
    return backup_root() / ".maintenance-lock"


def backup_in_progress() -> bool:
    return maintenance_lock_path().is_file()


def _safe_id(value: str) -> str:
    value = str(value or "")
    if not SAFE_ID.fullmatch(value):
        raise BackupServiceError("Invalid backup identifier.")
    return value


def metadata_path(backup_id: str) -> Path:
    return backup_root() / f"{_safe_id(backup_id)}.json"


def bundle_path(backup_id: str) -> Path:
    return backup_root() / f"{_safe_id(backup_id)}.mvbackup"


def read_metadata(path: Path) -> dict | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict) or not SAFE_ID.fullmatch(str(data.get("id") or "")):
        return None
    bundle = bundle_path(data["id"])
    data["download_available"] = bundle.is_file() and data.get("status") == "complete"
    data["restore_command"] = (
        f"python3 scripts/restore.py --sudo --backup-id {data['id']}"
        if data["download_available"] else ""
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
    path = metadata_path(backup_id)
    item = read_metadata(path) if path.is_file() else None
    if not item:
        raise BackupServiceError("Backup not found.")
    return item


def delete_backup(backup_id: str):
    item = get_backup(backup_id)
    if item.get("status") == "running" or backup_in_progress():
        raise BackupServiceError("A backup is currently running.")
    bundle_path(backup_id).unlink(missing_ok=True)
    metadata_path(backup_id).unlink(missing_ok=True)


def call_agent(path: str, *, method="POST", timeout=8) -> dict:
    base = str(settings.MAKERVAULT_BACKUP_AGENT_URL).rstrip("/")
    parsed = urllib.parse.urlsplit(base)
    if (
        parsed.scheme != "http"
        or parsed.hostname not in {"backup-agent", "127.0.0.1", "localhost"}
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
    ):
        raise BackupServiceError(
            "MakerVault backup service URL must use plain HTTP to the internal backup-agent service."
        )
    request = urllib.request.Request(
        base + path,
        method=method,
        headers={
            "Authorization": f"Bearer {settings.SECRET_KEY}",
            "Accept": "application/json",
            "X-MakerVault-Version": str(settings.MAKERVAULT_VERSION),
        },
    )
    try:
        # URL scheme/host are constrained above; file/custom schemes cannot reach this call.
        with urllib.request.urlopen(request, timeout=timeout) as response:  # nosec B310
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        try:
            payload = json.loads(exc.read().decode("utf-8"))
        except Exception:
            payload = {}
        raise BackupServiceError(payload.get("error") or f"Backup service returned HTTP {exc.code}.") from exc
    except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError) as exc:
        raise BackupServiceError("MakerVault backup service is unavailable.") from exc
    if not isinstance(payload, dict):
        raise BackupServiceError("MakerVault backup service returned an invalid response.")
    return payload


def create_backup() -> dict:
    return call_agent("/backup", timeout=10)


def validate_backup(backup_id: str) -> dict:
    _safe_id(backup_id)
    return call_agent(f"/validate/{backup_id}", timeout=120)


class BackupMaintenanceMiddleware:
    """Make the normal web UI read-only while a consistent backup is captured."""

    SAFE_METHODS = {"GET", "HEAD", "OPTIONS", "TRACE"}

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.method not in self.SAFE_METHODS and backup_in_progress():
            message = "MakerVault is briefly read-only while a backup is being created. Try again when the backup finishes."
            if request.path.startswith("/api/"):
                return JsonResponse({"error": message, "code": "backup_in_progress"}, status=503)
            return HttpResponse(message, status=503, content_type="text/plain; charset=utf-8")
        return self.get_response(request)
