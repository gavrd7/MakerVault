#!/usr/bin/env python3
"""Internal MakerVault backup agent.

Runs only on the private Compose network. It never receives the Docker socket.
The web application authenticates with MAKERVAULT_BACKUP_TOKEN and the agent
writes bundles to the shared backup volume.
"""
from __future__ import annotations

import argparse
import hashlib
import hmac
import http.server
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import subprocess
import tarfile
import tempfile
import threading
import time
import traceback
import uuid


BACKUP_ROOT = Path(os.environ.get("BACKUP_ROOT", "/backups"))
MEDIA_ROOT = Path(os.environ.get("SOURCE_MEDIA_ROOT", "/source/media"))
KEY_ROOT = Path(os.environ.get("SOURCE_KEY_ROOT", "/source/keys"))
CONFIG_ROOT = Path(os.environ.get("SOURCE_CONFIG_ROOT", "/source/config"))
LOCK_FILE = BACKUP_ROOT / ".maintenance-lock"
TOKEN = os.environ.get("MAKERVAULT_BACKUP_TOKEN", "")
HOST = os.environ.get("BACKUP_AGENT_HOST", "0.0.0.0")
PORT = int(os.environ.get("BACKUP_AGENT_PORT", "9784"))
FORMAT_VERSION = 2
_state_lock = threading.Lock()
_running_id = ""


class BackupError(RuntimeError):
    pass


def utc_stamp() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def safe_id(value: str) -> str:
    value = str(value or "")
    if not value or any(ch not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_" for ch in value):
        raise BackupError("Invalid backup identifier.")
    return value


def metadata_path(backup_id: str) -> Path:
    return BACKUP_ROOT / f"{safe_id(backup_id)}.json"


def bundle_path(backup_id: str) -> Path:
    return BACKUP_ROOT / f"{safe_id(backup_id)}.mvbackup"


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


def digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            value.update(chunk)
    return value.hexdigest()


def run(command, *, env=None, stdin=None, capture=False):
    try:
        return subprocess.run(
            command,
            check=True,
            env=env,
            stdin=stdin,
            stdout=subprocess.PIPE if capture else None,
            stderr=subprocess.PIPE if capture else None,
        )
    except subprocess.CalledProcessError as exc:
        detail = ""
        if exc.stderr:
            detail = exc.stderr.decode("utf-8", "replace").strip().splitlines()[-1]
        raise BackupError(detail or f"Command failed: {command[0]}") from exc


def db_env() -> dict:
    env = os.environ.copy()
    env["PGPASSWORD"] = os.environ.get("POSTGRES_PASSWORD", "")
    return env


def database_args() -> list[str]:
    return [
        "-h", os.environ.get("DATABASE_HOST", "postgres"),
        "-p", os.environ.get("DATABASE_PORT", "5432"),
        "-U", os.environ.get("POSTGRES_USER", "makervault"),
        "-d", os.environ.get("POSTGRES_DB", "makervault"),
    ]


def archive_directory(source: Path, target: Path):
    with tarfile.open(target, "w:gz") as archive:
        for child in sorted(source.iterdir()) if source.exists() else []:
            archive.add(child, arcname=child.name, recursive=True)


def check_tar(path: Path):
    with tarfile.open(path, "r:gz") as archive:
        for member in archive:
            member_path = PurePosixPath(member.name)
            if member_path.is_absolute() or ".." in member_path.parts:
                raise BackupError(f"Unsafe archive path in {path.name}.")
            if member.isfile():
                handle = archive.extractfile(member)
                if handle:
                    while handle.read(1024 * 1024):
                        pass


def config_files(work: Path):
    for name in (".env", "compose.yaml", "compose.override.yaml", "docker-compose.yml", "docker-compose.yaml"):
        source = CONFIG_ROOT / name
        if source.is_file():
            shutil.copyfile(source, work / name)


def create_bundle(*, backup_id=None, label="manual") -> dict:
    global _running_id
    BACKUP_ROOT.mkdir(parents=True, exist_ok=True)
    backup_id = safe_id(backup_id or time.strftime("%Y%m%d-%H%M%S", time.gmtime()) + "-" + uuid.uuid4().hex[:8])

    with _state_lock:
        if _running_id:
            raise BackupError("Another backup is already running.")
        _running_id = backup_id

    work = BACKUP_ROOT / f".working-{backup_id}"
    bundle = bundle_path(backup_id)
    created = utc_stamp()
    write_metadata(
        backup_id,
        id=backup_id,
        label=label,
        filename=bundle.name,
        status="running",
        verified=False,
        created_at=created,
        finished_at="",
        size_bytes=0,
        error="",
        format_version=FORMAT_VERSION,
    )
    LOCK_FILE.write_text(json.dumps({"id": backup_id, "created_at": created}), encoding="utf-8")
    os.chmod(LOCK_FILE, 0o600)

    try:
        if work.exists():
            shutil.rmtree(work)
        work.mkdir(mode=0o700)
        time.sleep(1.0)

        dump = work / "database.dump"
        with dump.open("wb") as output:
            try:
                subprocess.run(
                    ["pg_dump", *database_args(), "-Fc"],
                    check=True,
                    env=db_env(),
                    stdout=output,
                    stderr=subprocess.PIPE,
                )
            except subprocess.CalledProcessError as exc:
                detail = exc.stderr.decode("utf-8", "replace").strip().splitlines()[-1] if exc.stderr else ""
                raise BackupError(detail or "PostgreSQL backup failed.") from exc

        media_archive = work / "media.tar.gz"
        key_archive = work / "keys.tar.gz"
        archive_directory(MEDIA_ROOT, media_archive)
        archive_directory(KEY_ROOT, key_archive)
        config_files(work)

        recovery = {
            "format_version": FORMAT_VERSION,
            "created_utc": created,
            "label": label,
            "application_version": os.environ.get("MAKERVAULT_VERSION", ""),
            "database": {
                "name": os.environ.get("POSTGRES_DB", "makervault"),
                "user": os.environ.get("POSTGRES_USER", "makervault"),
            },
            "contents": ["database.dump", "media.tar.gz", "keys.tar.gz", "configuration"],
            "note": "Contains secrets and the private-storage key. Keep this bundle private.",
        }
        (work / "recovery-info.json").write_text(json.dumps(recovery, indent=2), encoding="utf-8")

        run(["pg_restore", "--list", str(dump)], capture=True)
        check_tar(media_archive)
        check_tar(key_archive)

        checksum_targets = sorted(path for path in work.iterdir() if path.name != "SHA256SUMS")
        (work / "SHA256SUMS").write_text(
            "".join(f"{digest(path)}  {path.name}\n" for path in checksum_targets),
            encoding="utf-8",
        )

        partial = bundle.with_suffix(".mvbackup.partial")
        if partial.exists():
            partial.unlink()
        with tarfile.open(partial, "w:gz") as archive:
            archive.add(work, arcname="makervault-backup")
        os.chmod(partial, 0o600)
        partial.replace(bundle)
        shutil.rmtree(work)

        result = write_metadata(
            backup_id,
            status="complete",
            verified=True,
            finished_at=utc_stamp(),
            size_bytes=bundle.stat().st_size,
            sha256=digest(bundle),
            error="",
        )
        return result
    except Exception as exc:
        write_metadata(
            backup_id,
            status="failed",
            verified=False,
            finished_at=utc_stamp(),
            error=str(exc)[:1000],
        )
        raise
    finally:
        try:
            LOCK_FILE.unlink(missing_ok=True)
        finally:
            with _state_lock:
                _running_id = ""
        if work.exists():
            shutil.rmtree(work, ignore_errors=True)


def _bundle_members(bundle: Path) -> dict[str, tarfile.TarInfo]:
    with tarfile.open(bundle, "r:gz") as archive:
        members = {}
        for member in archive.getmembers():
            path = PurePosixPath(member.name)
            if path.is_absolute() or ".." in path.parts:
                raise BackupError("Unsafe path in recovery bundle.")
            members[member.name] = member
        return members


def validate_bundle(bundle: Path) -> dict:
    if not bundle.is_file():
        raise BackupError("Backup bundle not found.")
    with tempfile.TemporaryDirectory(prefix="makervault-validate-") as directory:
        root = Path(directory)
        with tarfile.open(bundle, "r:gz") as archive:
            members = archive.getmembers()
            for member in members:
                path = PurePosixPath(member.name)
                if path.is_absolute() or ".." in path.parts:
                    raise BackupError("Unsafe path in recovery bundle.")
            archive.extractall(root, filter="data")
        backup = root / "makervault-backup"
        sums = backup / "SHA256SUMS"
        if not sums.is_file():
            raise BackupError("Recovery bundle has no checksum manifest.")
        for raw in sums.read_text(encoding="utf-8").splitlines():
            expected, sep, name = raw.partition("  ")
            target = backup / name
            if not sep or not target.is_file() or digest(target) != expected:
                raise BackupError(f"Checksum failed for {name or 'bundle member'}.")
        run(["pg_restore", "--list", str(backup / "database.dump")], capture=True)
        check_tar(backup / "media.tar.gz")
        check_tar(backup / "keys.tar.gz")
        info = json.loads((backup / "recovery-info.json").read_text(encoding="utf-8"))
        return {
            "valid": True,
            "format_version": info.get("format_version"),
            "created_utc": info.get("created_utc", ""),
            "application_version": info.get("application_version", ""),
            "size_bytes": bundle.stat().st_size,
            "sha256": digest(bundle),
        }


def clear_directory(path: Path):
    path.mkdir(parents=True, exist_ok=True)
    for child in list(path.iterdir()):
        if child.is_dir() and not child.is_symlink():
            shutil.rmtree(child)
        else:
            child.unlink()


def safe_extract_tar(path: Path, destination: Path):
    with tarfile.open(path, "r:gz") as archive:
        for member in archive.getmembers():
            item = PurePosixPath(member.name)
            if item.is_absolute() or ".." in item.parts:
                raise BackupError(f"Unsafe path in {path.name}.")
        archive.extractall(destination, filter="data")


def restore_bundle(bundle: Path):
    validate_bundle(bundle)
    with tempfile.TemporaryDirectory(prefix="makervault-restore-") as directory:
        root = Path(directory)
        with tarfile.open(bundle, "r:gz") as archive:
            archive.extractall(root, filter="data")
        backup = root / "makervault-backup"

        run([
            "pg_restore", *database_args(),
            "--clean", "--if-exists", "--no-owner", "--no-privileges", "--exit-on-error",
            str(backup / "database.dump"),
        ], env=db_env())

        clear_directory(MEDIA_ROOT)
        clear_directory(KEY_ROOT)
        safe_extract_tar(backup / "media.tar.gz", MEDIA_ROOT)
        safe_extract_tar(backup / "keys.tar.gz", KEY_ROOT)


class Handler(http.server.BaseHTTPRequestHandler):
    server_version = "MakerVaultBackup/1"

    def log_message(self, format, *args):
        print(f"[backup-agent] {self.address_string()} {format % args}", flush=True)

    def _authorised(self) -> bool:
        supplied = self.headers.get("Authorization", "")
        expected = f"Bearer {TOKEN}" if TOKEN else ""
        return bool(expected) and hmac.compare_digest(supplied, expected)

    def _json(self, status: int, payload: dict):
        data = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if self.path == "/healthz":
            return self._json(200, {"status": "ok"})
        if not self._authorised():
            return self._json(403, {"error": "Forbidden."})
        if self.path == "/status":
            with _state_lock:
                current = _running_id
            return self._json(200, {"running": bool(current), "backup_id": current})
        return self._json(404, {"error": "Not found."})

    def do_POST(self):
        if not self._authorised():
            return self._json(403, {"error": "Forbidden."})
        if self.path == "/backup":
            try:
                with _state_lock:
                    if _running_id:
                        return self._json(409, {"error": "Another backup is already running.", "backup_id": _running_id})
                backup_id = time.strftime("%Y%m%d-%H%M%S", time.gmtime()) + "-" + uuid.uuid4().hex[:8]
                thread = threading.Thread(
                    target=self._background_backup,
                    kwargs={"backup_id": backup_id},
                    daemon=True,
                )
                thread.start()
                return self._json(202, {"backup_id": backup_id, "status": "starting"})
            except Exception as exc:
                return self._json(500, {"error": str(exc)})
        if self.path.startswith("/validate/"):
            try:
                backup_id = safe_id(self.path.rsplit("/", 1)[-1])
                result = validate_bundle(bundle_path(backup_id))
                return self._json(200, result)
            except Exception as exc:
                return self._json(400, {"error": str(exc), "valid": False})
        return self._json(404, {"error": "Not found."})

    @staticmethod
    def _background_backup(backup_id):
        try:
            create_bundle(backup_id=backup_id, label="MakerVault UI")
        except Exception:
            traceback.print_exc()


def serve():
    BACKUP_ROOT.mkdir(parents=True, exist_ok=True)
    server = http.server.ThreadingHTTPServer((HOST, PORT), Handler)
    print(f"MakerVault backup agent listening on {HOST}:{PORT}", flush=True)
    server.serve_forever()


def main():
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command")
    sub.add_parser("serve")
    backup_cmd = sub.add_parser("backup")
    backup_cmd.add_argument("--id")
    backup_cmd.add_argument("--label", default="manual")
    validate_cmd = sub.add_parser("validate")
    validate_cmd.add_argument("--id", required=True)
    restore_cmd = sub.add_parser("restore")
    restore_cmd.add_argument("--id", required=True)
    args = parser.parse_args()

    if args.command in (None, "serve"):
        serve()
        return 0
    if args.command == "backup":
        result = create_bundle(backup_id=args.id, label=args.label)
        print(json.dumps(result))
        return 0
    if args.command == "validate":
        print(json.dumps(validate_bundle(bundle_path(args.id))))
        return 0
    if args.command == "restore":
        restore_bundle(bundle_path(args.id))
        print(json.dumps({"restored": True, "backup_id": args.id}))
        return 0
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
