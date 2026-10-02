#!/usr/bin/env python3
"""One-command, quiesced backup of the supplied local MakerVault Docker stack."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import tarfile
import tempfile
from datetime import datetime, timezone


class BackupError(Exception):
    pass


def run(command, *, output=None, input_file=None):
    result = subprocess.run(command, stdout=output or subprocess.PIPE, stdin=input_file,
                            stderr=subprocess.PIPE, check=False)
    if result.returncode:
        # Docker errors can include configuration values. Keep diagnostics local.
        raise BackupError(f"{command[-1] if command[-1] in ('start', 'stop') else 'Backup operation'} failed (exit {result.returncode}). Check Docker availability, storage space and container logs.")
    return result.stdout


def environment(container):
    return dict(item.split("=", 1) for item in container["Config"].get("Env", []) if "=" in item)


def validate(app, database):
    app_env, db_env = environment(app), environment(database)
    if not app["State"]["Running"] or not database["State"]["Running"]:
        raise BackupError("Start MakerVault and PostgreSQL before creating a backup.")
    if app["Id"] == database["Id"]:
        raise BackupError("Application and database must be different containers.")
    labels = app["Config"].get("Labels") or {}
    db_labels = database["Config"].get("Labels") or {}
    project = labels.get("com.docker.compose.project")
    if not project or project != db_labels.get("com.docker.compose.project"):
        raise BackupError("Application and database must belong to the same Compose project.")
    aliases = {database["Name"].lstrip("/")}
    for network in database.get("NetworkSettings", {}).get("Networks", {}).values():
        aliases.update(network.get("Aliases") or [])
    if app_env.get("DATABASE_HOST", "postgres") not in aliases:
        raise BackupError("The app uses a different database host. Use the advanced backup procedure.")
    for key, default in (("POSTGRES_DB", "makervault"), ("POSTGRES_USER", "makervault")):
        if app_env.get(key, default) != db_env.get(key, default):
            raise BackupError("App/database settings differ. Use the advanced backup procedure.")
    if app_env.get("DATABASE_PORT", "5432") != "5432":
        raise BackupError("Custom database ports require the advanced backup procedure.")
    mounts = {item["Destination"] for item in app["Mounts"]}
    if not {"/app/media", "/app/keys"}.issubset(mounts):
        raise BackupError("Expected media/key mounts are missing. Use the advanced backup procedure.")
    key_path = Path(app_env.get("MAKERVAULT_STORAGE_KEY_FILE", "/app/keys/private_storage.key"))
    if not app_env.get("MAKERVAULT_STORAGE_KEY") and (".." in key_path.parts or not key_path.is_relative_to("/app/keys")):
        raise BackupError("The encryption key is outside the standard key mount. Use the advanced procedure.")
    return app_env, db_env


def digest(path):
    checksum = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            checksum.update(chunk)
    return checksum.hexdigest()


def backup(args):
    docker = (["sudo"] if args.sudo else []) + ["docker"]
    source = Path(args.source_dir).resolve()
    if not (source / ".env").is_file() or not (source / "compose.yaml").is_file():
        raise BackupError("Run from the MakerVault checkout containing .env and compose.yaml.")
    # Resolve containers before stopping anything. Capture actual runtime settings,
    # including inline keys, instead of assuming .env still matches the running app.
    print("1/5 Checking containers and backup destination...", flush=True)
    app = json.loads(run(docker + ["inspect", args.app_container]))[0]
    database = json.loads(run(docker + ["inspect", args.database_container]))[0]
    app_env, db_env = validate(app, database)
    destination = Path(args.destination).expanduser().resolve()
    for mount in app["Mounts"] + database["Mounts"]:
        if destination.is_relative_to(Path(mount["Source"]).resolve()):
            raise BackupError("Choose a backup destination outside the app/database storage mounts.")
    destination.mkdir(parents=True, exist_ok=True, mode=0o700)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    work = Path(tempfile.mkdtemp(prefix=f".incomplete-{stamp}-", dir=destination))
    bundle = destination / f"makervault-{stamp}-{work.name.rsplit('-', 1)[-1]}.tar.gz"
    partial = bundle.with_suffix(bundle.suffix + ".partial")
    restart_needed = False
    try:
        for name in (".env", "compose.yaml", "compose.override.yaml", "compose.override.yml", "docker-compose.override.yml"):
            if (source / name).is_file():
                shutil.copyfile(source / name, work / name)
        revision = subprocess.run(["git", "-C", str(source), "rev-parse", "HEAD"], capture_output=True, check=False)
        if revision.returncode:
            raise BackupError("Cannot identify the checkout revision; use a Git checkout or the advanced procedure.")
        (work / "source-commit.txt").write_bytes(revision.stdout)
        (work / "runtime-environment.json").write_text(json.dumps({"app": app_env, "postgres": db_env}, indent=2))
        (work / "recovery-info.json").write_text(json.dumps({
            "created_utc": stamp, "application_image_id": app["Image"],
            "database_image_id": database["Image"],
            "note": "source-commit is the checkout revision; verify it matches the deployed image. Runtime environment contains secrets. Redis queue is deliberately excluded.",
        }, indent=2))
        print("2/5 Pausing MakerVault briefly for a consistent backup...", flush=True)
        restart_needed = True
        run(docker + ["stop", "--time", "60", app["Id"]])
        state = json.loads(run(docker + ["inspect", app["Id"]]))[0]["State"]
        if state["Running"]:
            raise BackupError("MakerVault did not stop; backup cancelled.")
        print("3/5 Saving database, media and encryption keys...", flush=True)
        with (work / "database.dump").open("wb") as output:
            run(docker + ["exec", database["Id"], "pg_dump", "-U", db_env.get("POSTGRES_USER", "makervault"),
                          "-d", db_env.get("POSTGRES_DB", "makervault"), "-Fc"], output=output)
        for name in ("media", "keys"):
            with (work / f"{name}.tar.gz").open("wb") as output:
                run(docker + ["run", "--rm", "--network", "none", "--volumes-from", app["Id"] + ":ro",
                              "--entrypoint", "tar", app["Image"], "-C", f"/app/{name}", "-czf", "-", "."], output=output)
        print("4/5 Checking archives and restarting MakerVault...", flush=True)
        with (work / "database.dump").open("rb") as input_file:
            run(docker + ["exec", "-i", database["Id"], "pg_restore", "--list"], input_file=input_file)
        for name in ("media", "keys"):
            with tarfile.open(work / f"{name}.tar.gz", "r:gz") as archive:
                for member in archive:
                    if member.isfile():
                        with archive.extractfile(member) as handle:
                            while handle.read(1024 * 1024):
                                pass
        if not app_env.get("MAKERVAULT_STORAGE_KEY"):
            key_name = str(Path(app_env.get("MAKERVAULT_STORAGE_KEY_FILE", "/app/keys/private_storage.key")).relative_to("/app/keys"))
            with tarfile.open(work / "keys.tar.gz", "r:gz") as archive:
                members = {m.name.removeprefix("./"): m for m in archive}
                if key_name not in members or not members[key_name].isfile() or members[key_name].size == 0:
                    raise BackupError("The key archive is missing the configured key. Backup is incomplete.")
        run(docker + ["start", app["Id"]])
        restart_needed = False
        print("5/5 Packaging one protected recovery bundle...", flush=True)
        files = sorted(work.iterdir())
        (work / "SHA256SUMS").write_text("".join(f"{digest(p)}  {p.name}\n" for p in files))
        with tarfile.open(partial, "w:gz") as archive:
            archive.add(work, arcname="makervault-backup")
        os.chmod(partial, 0o600)
        partial.replace(bundle)
        shutil.rmtree(work)
        print(f"Backup complete: {bundle}\nMakerVault has been restarted; allow it to become healthy. Copy this bundle off the server.\nThe bundle contains secrets and the encryption key; it is protected by file permissions, not encrypted.")
        return bundle
    finally:
        if restart_needed:
            print("Restarting MakerVault after the interrupted backup...", flush=True)
            try:
                run(docker + ["start", app["Id"]])
            except BackupError:
                print("Automatic restart failed. Run: sudo docker start " + args.app_container, file=sys.stderr)
        if work.exists():
            print(f"Incomplete backup retained at {work}; do not use it as a recovery set.", file=sys.stderr)


def main():
    parser = argparse.ArgumentParser(description="Create one consistent MakerVault recovery bundle; briefly pauses the app and restarts it even on ordinary failures.")
    parser.add_argument("--sudo", action="store_true", help="Run Docker commands through sudo")
    parser.add_argument("--destination", default=str(Path.home() / "makervault-backups"))
    parser.add_argument("--source-dir", default=str(Path(__file__).resolve().parent.parent))
    parser.add_argument("--app-container", default="makervault")
    parser.add_argument("--database-container", default="makervault-postgres")
    args = parser.parse_args()
    os.umask(0o077)
    def interrupted(signum, frame):
        raise KeyboardInterrupt("Backup interrupted")
    signal.signal(signal.SIGTERM, interrupted)
    try:
        backup(args)
    except (BackupError, OSError, tarfile.TarError, KeyboardInterrupt) as exc:
        print(f"Backup not completed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
