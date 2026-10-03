from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import subprocess
import tarfile
import tempfile
import time
import uuid

from django.conf import settings
from django.db import connections


FORMAT_VERSION = 3
SAFE_ID = re.compile(r"^[A-Za-z0-9_-]+$")


class BackupBundleError(RuntimeError):
    pass


def utc_stamp() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def backup_root() -> Path:
    root = Path(settings.MAKERVAULT_BACKUP_ROOT)
    root.mkdir(parents=True, exist_ok=True)
    return root


def media_root() -> Path:
    return Path(settings.MEDIA_ROOT)


def tls_root() -> Path:
    return Path(os.getenv("MAKERVAULT_TLS_ROOT", "/app/keys/tls"))


def key_root() -> Path:
    path = settings.MAKERVAULT_STORAGE_KEY_FILE
    if path:
        resolved = Path(path).resolve()
        try:
            resolved.relative_to(Path("/app/keys"))
            return Path("/app/keys")
        except ValueError:
            # The normal GUI path rejects custom key mounts, but keeping the
            # engine path-aware makes advanced/manual recovery explicit.
            return resolved.parent
    return Path("/app/keys")


def maintenance_lock_path() -> Path:
    return backup_root() / ".maintenance-lock"


def safe_id(value: str) -> str:
    value = str(value or "")
    if not SAFE_ID.fullmatch(value):
        raise BackupBundleError("Invalid backup identifier.")
    return value


def metadata_path(backup_id: str) -> Path:
    return backup_root() / f"{safe_id(backup_id)}.json"


def bundle_path(backup_id: str) -> Path:
    return backup_root() / f"{safe_id(backup_id)}.mvbackup"


def digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            value.update(chunk)
    return value.hexdigest()


def write_metadata(backup_id: str, **values) -> dict:
    path = metadata_path(backup_id)
    current = {}
    if path.is_file():
        try:
            current = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            current = {}
    current.update(values)
    temp = path.with_suffix(".json.tmp")
    temp.write_text(json.dumps(current, indent=2, sort_keys=True), encoding="utf-8")
    os.chmod(temp, 0o600)
    temp.replace(path)
    return current


def read_metadata_file(path: Path) -> dict | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict) or not SAFE_ID.fullmatch(str(data.get("id") or "")):
        return None
    return data


def _claim_lock(backup_id: str, created_at: str):
    lock = maintenance_lock_path()
    payload = json.dumps({"id": backup_id, "created_at": created_at}).encode("utf-8")
    try:
        fd = os.open(lock, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError as exc:
        raise BackupBundleError("Another backup is already running.") from exc
    try:
        os.write(fd, payload)
    finally:
        os.close(fd)


def _lock_owner() -> str:
    path = maintenance_lock_path()
    if not path.is_file():
        return ""
    try:
        return str(json.loads(path.read_text(encoding="utf-8")).get("id") or "")
    except (OSError, json.JSONDecodeError):
        return ""


def release_lock(backup_id: str | None = None):
    lock = maintenance_lock_path()
    if not lock.exists():
        return
    owner = _lock_owner()
    if backup_id and owner and owner != backup_id:
        return
    lock.unlink(missing_ok=True)


def prepare_backup(*, backup_id: str | None = None, label: str = "MakerVault UI") -> dict:
    backup_id = safe_id(
        backup_id
        or time.strftime("%Y%m%d-%H%M%S", time.gmtime()) + "-" + uuid.uuid4().hex[:8]
    )
    created = utc_stamp()
    _claim_lock(backup_id, created)
    try:
        return write_metadata(
            backup_id,
            id=backup_id,
            label=label,
            filename=bundle_path(backup_id).name,
            status="running",
            verified=False,
            created_at=created,
            finished_at="",
            size_bytes=0,
            error="",
            format_version=FORMAT_VERSION,
            application_version=str(settings.MAKERVAULT_VERSION),
        )
    except Exception:
        release_lock(backup_id)
        raise


def mark_failed(backup_id: str, error: str):
    write_metadata(
        backup_id,
        status="failed",
        verified=False,
        finished_at=utc_stamp(),
        error=str(error)[:1000],
    )


def _db_env() -> dict:
    env = os.environ.copy()
    env["PGPASSWORD"] = str(settings.DATABASES["default"].get("PASSWORD") or "")
    return env


def _database_args() -> list[str]:
    database = settings.DATABASES["default"]
    return [
        "-h", str(database.get("HOST") or "postgres"),
        "-p", str(database.get("PORT") or "5432"),
        "-U", str(database.get("USER") or "makervault"),
        "-d", str(database.get("NAME") or "makervault"),
    ]


def _run(command: list[str], *, capture=False):
    try:
        return subprocess.run(
            command,
            check=True,
            env=_db_env(),
            stdout=subprocess.PIPE if capture else None,
            stderr=subprocess.PIPE if capture else None,
        )
    except subprocess.CalledProcessError as exc:
        detail = ""
        if exc.stderr:
            detail = exc.stderr.decode("utf-8", "replace").strip().splitlines()[-1]
        raise BackupBundleError(detail or f"Command failed: {command[0]}") from exc


def _archive_directory(source: Path, target: Path, *, exclude_names: set[str] | None = None):
    excluded = exclude_names or set()
    with tarfile.open(target, "w:gz") as archive:
        if source.exists():
            for child in sorted(source.iterdir()):
                if child.name in excluded:
                    continue
                archive.add(child, arcname=child.name, recursive=True)


def _check_tar(path: Path):
    with tarfile.open(path, "r:gz") as archive:
        for member in archive.getmembers():
            item = PurePosixPath(member.name)
            if item.is_absolute() or ".." in item.parts:
                raise BackupBundleError(f"Unsafe archive path in {path.name}.")
            if not (member.isfile() or member.isdir()):
                raise BackupBundleError(f"Unsupported archive entry in {path.name}.")
            if member.isfile():
                handle = archive.extractfile(member)
                if handle:
                    while handle.read(1024 * 1024):
                        pass


def _recovery_env_keys() -> list[str]:
    template = Path("/app/.env.example")
    keys: list[str] = []
    if template.is_file():
        for raw in template.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key = line.split("=", 1)[0].strip()
            if re.fullmatch(r"[A-Z][A-Z0-9_]*", key):
                keys.append(key)
    return keys


def recovery_env_text() -> str:
    lines = [
        "# Recovered by MakerVault from the environment used to create this backup.",
        "# Review host paths, hostnames and reverse-proxy settings on a replacement server.",
        "",
    ]
    for key in _recovery_env_keys():
        if key not in os.environ:
            continue
        value = os.environ.get(key, "")
        if value == "":
            lines.append(f"{key}=")
        else:
            lines.append(f"{key}={json.dumps(value)}")
    return "\n".join(lines) + "\n"


def create_prepared_bundle(backup_id: str) -> dict:
    backup_id = safe_id(backup_id)
    owner = _lock_owner()
    if owner != backup_id:
        raise BackupBundleError("Backup lock does not belong to this backup job.")

    meta = read_metadata_file(metadata_path(backup_id)) or {}
    work = backup_root() / f".working-{backup_id}"
    bundle = bundle_path(backup_id)

    try:
        if work.exists():
            shutil.rmtree(work)
        work.mkdir(mode=0o700)

        dump = work / "database.dump"
        with dump.open("wb") as output:
            try:
                subprocess.run(
                    ["pg_dump", *_database_args(), "-Fc"],
                    check=True,
                    env=_db_env(),
                    stdout=output,
                    stderr=subprocess.PIPE,
                )
            except subprocess.CalledProcessError as exc:
                detail = exc.stderr.decode("utf-8", "replace").strip().splitlines()[-1] if exc.stderr else ""
                raise BackupBundleError(detail or "PostgreSQL backup failed.") from exc

        media_archive = work / "media.tar.gz"
        key_archive = work / "keys.tar.gz"
        tls_archive = work / "tls.tar.gz"
        _archive_directory(media_root(), media_archive)
        tls = tls_root()
        keys = key_root()
        exclude_key_names = {"tls"} if tls.parent == keys else set()
        _archive_directory(keys, key_archive, exclude_names=exclude_key_names)
        _archive_directory(tls, tls_archive)
        (work / ".env").write_text(recovery_env_text(), encoding="utf-8")

        recovery = {
            "format_version": FORMAT_VERSION,
            "created_utc": meta.get("created_at") or utc_stamp(),
            "label": meta.get("label") or "MakerVault backup",
            "application_version": str(settings.MAKERVAULT_VERSION),
            "database": {
                "name": str(settings.DATABASES["default"].get("NAME") or "makervault"),
                "user": str(settings.DATABASES["default"].get("USER") or "makervault"),
            },
            "contents": ["database.dump", "media.tar.gz", "keys.tar.gz", "tls.tar.gz", ".env"],
            "note": "Contains secrets and the private-storage key. Keep this bundle private.",
        }
        (work / "recovery-info.json").write_text(json.dumps(recovery, indent=2), encoding="utf-8")

        _run(["pg_restore", "--list", str(dump)], capture=True)
        _check_tar(media_archive)
        _check_tar(key_archive)
        _check_tar(tls_archive)

        checksum_targets = sorted(path for path in work.iterdir() if path.name != "SHA256SUMS")
        (work / "SHA256SUMS").write_text(
            "".join(f"{digest(path)}  {path.name}\n" for path in checksum_targets),
            encoding="utf-8",
        )

        partial = bundle.with_suffix(".mvbackup.partial")
        partial.unlink(missing_ok=True)
        with tarfile.open(partial, "w:gz") as archive:
            archive.add(work, arcname="makervault-backup")
        os.chmod(partial, 0o600)
        partial.replace(bundle)

        return write_metadata(
            backup_id,
            status="complete",
            verified=True,
            finished_at=utc_stamp(),
            size_bytes=bundle.stat().st_size,
            sha256=digest(bundle),
            error="",
        )
    except Exception as exc:
        mark_failed(backup_id, str(exc))
        raise
    finally:
        release_lock(backup_id)
        if work.exists():
            shutil.rmtree(work, ignore_errors=True)


def create_bundle(*, backup_id: str | None = None, label: str = "manual") -> dict:
    item = prepare_backup(backup_id=backup_id, label=label)
    return create_prepared_bundle(item["id"])


def validate_bundle(bundle: Path) -> dict:
    if not bundle.is_file():
        raise BackupBundleError("Backup bundle not found.")
    with tempfile.TemporaryDirectory(prefix="makervault-validate-") as directory:
        root = Path(directory)
        try:
            with tarfile.open(bundle, "r:gz") as archive:
                for member in archive.getmembers():
                    item = PurePosixPath(member.name)
                    if item.is_absolute() or ".." in item.parts:
                        raise BackupBundleError("Unsafe path in recovery bundle.")
                    if not (member.isfile() or member.isdir()):
                        raise BackupBundleError("Recovery bundle contains an unsupported archive entry.")
                archive.extractall(root, filter="data")
        except tarfile.TarError as exc:
            raise BackupBundleError(f"Recovery bundle is unreadable: {exc}") from exc

        backup = root / "makervault-backup"
        sums = backup / "SHA256SUMS"
        if not sums.is_file():
            raise BackupBundleError("Recovery bundle has no checksum manifest.")
        for raw in sums.read_text(encoding="utf-8").splitlines():
            expected, sep, name = raw.partition("  ")
            if not sep or "/" in name or "\\" in name or name in {"", ".", ".."}:
                raise BackupBundleError("Recovery checksum manifest contains an invalid filename.")
            target = backup / name
            if not target.is_file() or digest(target) != expected:
                raise BackupBundleError(f"Checksum failed for {name or 'bundle member'}.")

        _run(["pg_restore", "--list", str(backup / "database.dump")], capture=True)
        _check_tar(backup / "media.tar.gz")
        _check_tar(backup / "keys.tar.gz")
        tls_archive = backup / "tls.tar.gz"
        if tls_archive.is_file():
            _check_tar(tls_archive)
        info = json.loads((backup / "recovery-info.json").read_text(encoding="utf-8"))
        return {
            "valid": True,
            "format_version": info.get("format_version"),
            "created_utc": info.get("created_utc", ""),
            "application_version": info.get("application_version", ""),
            "size_bytes": bundle.stat().st_size,
            "sha256": digest(bundle),
        }


def validate_backup_id(backup_id: str) -> dict:
    return validate_bundle(bundle_path(safe_id(backup_id)))


def register_bundle(backup_id: str, *, label: str = "Imported recovery bundle") -> dict:
    backup_id = safe_id(backup_id)
    result = validate_backup_id(backup_id)
    return write_metadata(
        backup_id,
        id=backup_id,
        label=label,
        filename=bundle_path(backup_id).name,
        status="complete",
        verified=True,
        created_at=result.get("created_utc") or utc_stamp(),
        finished_at=utc_stamp(),
        size_bytes=result.get("size_bytes") or 0,
        sha256=result.get("sha256") or "",
        error="",
        format_version=result.get("format_version") or FORMAT_VERSION,
        application_version=result.get("application_version") or "",
    )


def _clear_directory(path: Path, *, preserve_names: set[str] | None = None):
    preserved = preserve_names or set()
    path.mkdir(parents=True, exist_ok=True)
    for child in list(path.iterdir()):
        if child.name in preserved:
            continue
        if child.is_dir() and not child.is_symlink():
            shutil.rmtree(child)
        else:
            child.unlink()


def _safe_extract_tar(path: Path, destination: Path):
    with tarfile.open(path, "r:gz") as archive:
        for member in archive.getmembers():
            item = PurePosixPath(member.name)
            if item.is_absolute() or ".." in item.parts:
                raise BackupBundleError(f"Unsafe path in {path.name}.")
            if not (member.isfile() or member.isdir()):
                raise BackupBundleError(f"Unsupported archive entry in {path.name}.")
        archive.extractall(destination, filter="data")


def restore_bundle(backup_id: str):
    backup_id = safe_id(backup_id)
    bundle = bundle_path(backup_id)
    validate_bundle(bundle)
    with tempfile.TemporaryDirectory(prefix="makervault-restore-") as directory:
        root = Path(directory)
        with tarfile.open(bundle, "r:gz") as archive:
            archive.extractall(root, filter="data")
        backup = root / "makervault-backup"

        connections.close_all()
        _run([
            "pg_restore", *_database_args(),
            "--clean", "--if-exists", "--no-owner", "--no-privileges", "--exit-on-error",
            str(backup / "database.dump"),
        ])

        tls_archive = backup / "tls.tar.gz"
        tls = tls_root()
        keys = key_root()

        _clear_directory(media_root())
        preserve_key_names = {"tls"} if not tls_archive.is_file() and tls.parent == keys else set()
        _clear_directory(keys, preserve_names=preserve_key_names)
        _safe_extract_tar(backup / "media.tar.gz", media_root())
        _safe_extract_tar(backup / "keys.tar.gz", keys)

        # Format v3+ carries MakerVault-owned TLS identity separately even though
        # its live files now sit under KEY_STORAGE/tls. Older bundles do not, so
        # preserve an existing local TLS identity when restoring a legacy bundle.
        if tls_archive.is_file():
            _clear_directory(tls)
            _safe_extract_tar(tls_archive, tls)


def recover_interrupted_backups() -> int:
    root = backup_root()
    changed = 0
    for path in root.glob("*.json"):
        item = read_metadata_file(path)
        if not item or item.get("status") != "running":
            continue
        backup_id = str(item.get("id") or "")
        if not SAFE_ID.fullmatch(backup_id):
            continue
        mark_failed(backup_id, "MakerVault restarted before this backup completed.")
        changed += 1
    release_lock()
    for path in root.glob(".working-*"):
        if path.is_dir():
            shutil.rmtree(path, ignore_errors=True)
    return changed
