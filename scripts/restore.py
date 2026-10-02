#!/usr/bin/env python3
"""Guarded MakerVault restore helper for the standard Docker Compose deployment."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import subprocess
import sys
import tarfile
import time


class RestoreError(RuntimeError):
    pass


def run(command, *, capture=False, check=True):
    result = subprocess.run(
        command,
        check=False,
        text=True,
        stdout=subprocess.PIPE if capture else None,
        stderr=subprocess.PIPE if capture else None,
    )
    if check and result.returncode:
        detail = ""
        if capture:
            lines = (result.stderr or result.stdout or "").strip().splitlines()
            detail = lines[-1] if lines else ""
        raise RestoreError(detail or f"Command failed: {' '.join(command)}")
    return result


def stream_file(command, source: Path):
    with source.open("rb") as handle:
        result = subprocess.run(command, check=False, stdin=handle)
    if result.returncode:
        raise RestoreError("Could not import the recovery bundle into MakerVault backup storage.")


def compose_command(sudo: bool) -> list[str]:
    return (["sudo"] if sudo else []) + ["docker", "compose"]


def parse_last_json(output: str) -> dict:
    for line in reversed((output or "").splitlines()):
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            return value
    return {}


def digest_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def digest_file(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            value.update(chunk)
    return value.hexdigest()


def inspect_local_bundle(bundle: Path) -> bytes | None:
    """Verify inner checksums without extracting and return the bundled .env when present."""
    if not bundle.is_file():
        raise RestoreError(f"Recovery bundle not found: {bundle}")
    try:
        with tarfile.open(bundle, "r:gz") as archive:
            members = {}
            for member in archive.getmembers():
                path = PurePosixPath(member.name)
                if path.is_absolute() or ".." in path.parts or member.issym() or member.islnk():
                    raise RestoreError("Recovery bundle contains an unsafe path or link.")
                members[member.name] = member

            sums_member = members.get("makervault-backup/SHA256SUMS")
            if not sums_member or not sums_member.isfile():
                raise RestoreError("Recovery bundle has no checksum manifest.")
            handle = archive.extractfile(sums_member)
            if not handle:
                raise RestoreError("Recovery checksum manifest is unreadable.")
            lines = handle.read(1024 * 1024).decode("utf-8").splitlines()

            for raw in lines:
                expected, sep, name = raw.partition("  ")
                if not sep or "/" in name or "\\" in name or name in {"", ".", ".."}:
                    raise RestoreError("Recovery checksum manifest contains an invalid filename.")
                member = members.get(f"makervault-backup/{name}")
                if not member or not member.isfile():
                    raise RestoreError(f"Recovery bundle is missing {name}.")
                file_handle = archive.extractfile(member)
                if not file_handle:
                    raise RestoreError(f"Recovery bundle cannot read {name}.")
                value = hashlib.sha256()
                while chunk := file_handle.read(1024 * 1024):
                    value.update(chunk)
                if value.hexdigest() != expected:
                    raise RestoreError(f"Recovery checksum failed for {name}.")

            env_member = members.get("makervault-backup/.env")
            if env_member and env_member.isfile():
                if env_member.size > 1024 * 1024:
                    raise RestoreError("Bundled .env is unexpectedly large.")
                env_handle = archive.extractfile(env_member)
                return env_handle.read() if env_handle else None
            return None
    except (tarfile.TarError, UnicodeDecodeError, OSError) as exc:
        raise RestoreError(f"Recovery bundle is unreadable: {exc}") from exc


def env_ids(path: Path) -> tuple[int, int]:
    values = {}
    if path.is_file():
        for raw in path.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            values[key.strip()] = value.strip().strip('"').strip("'")
    try:
        return int(values.get("PUID", "1000")), int(values.get("PGID", "1000"))
    except ValueError as exc:
        raise RestoreError("PUID and PGID in .env must be numeric before restoring.") from exc


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Safely restore one MakerVault recovery bundle with an automatic pre-restore backup when replacing an existing installation."
    )
    source_group = parser.add_mutually_exclusive_group(required=True)
    source_group.add_argument("--backup-id", help="Backup identifier shown in MakerVault Settings > Backup & restore.")
    source_group.add_argument("--bundle", help="Path to an off-server .mvbackup bundle, including on a clean replacement host.")
    parser.add_argument("--sudo", action="store_true", help="Run Docker commands through sudo.")
    parser.add_argument("--yes", action="store_true", help="Skip the interactive backup-ID confirmation.")
    parser.add_argument("--source-dir", default=str(Path(__file__).resolve().parent.parent))
    args = parser.parse_args()

    source = Path(args.source_dir).resolve()
    if not (source / "compose.yaml").is_file():
        print("Restore not started: compose.yaml was not found in the MakerVault checkout.", file=sys.stderr)
        return 2

    docker = compose_command(args.sudo)
    base = [*docker, "-f", str(source / "compose.yaml"), "--project-directory", str(source)]
    env_file = source / ".env"

    bundle = Path(args.bundle).expanduser().resolve() if args.bundle else None
    if bundle:
        print("1/8 Verifying the off-server recovery bundle...", flush=True)
        try:
            bundled_env = inspect_local_bundle(bundle)
        except RestoreError as exc:
            print(f"Restore not started: {exc}", file=sys.stderr)
            return 2

        if not env_file.exists():
            if not bundled_env:
                print("Restore not started: the clean checkout has no .env and the bundle does not contain one.", file=sys.stderr)
                return 2
            env_file.write_bytes(bundled_env)
            os.chmod(env_file, 0o600)
            print("Recovered .env from the verified bundle because this checkout did not have one.", flush=True)
        else:
            print("Existing .env retained. The restore helper never silently overwrites current deployment configuration.", flush=True)

        backup_id = "imported-" + digest_file(bundle)[:16]
        try:
            print("2/8 Preparing the backup service and database...", flush=True)
            run([*base, "build", "backup-agent"])
            run([*base, "up", "-d", "--wait", "postgres", "redis"])
            puid, pgid = env_ids(env_file)
            stage = [
                *base, "run", "--rm", "--no-deps", "-T", "--user", "0:0",
                "--entrypoint", "sh", "backup-agent", "-c",
                'umask 077; cat > "/backups/$1.mvbackup"; chown "$2:$3" "/backups/$1.mvbackup"; chmod 600 "/backups/$1.mvbackup"',
                "sh", backup_id, str(puid), str(pgid),
            ]
            stream_file(stage, bundle)
            registered = run(
                [*base, "run", "--rm", "--no-deps", "backup-agent", "register", "--id", backup_id],
                capture=True,
                check=False,
            )
            if registered.returncode:
                detail = (registered.stderr or registered.stdout or "").strip()
                raise RestoreError(detail or "Could not register the imported recovery bundle.")
        except RestoreError as exc:
            print(f"Restore not started: {exc}", file=sys.stderr)
            return 2
        step_offset = 2
        total_steps = 8
    else:
        backup_id = str(args.backup_id or "").strip()
        step_offset = 0
        total_steps = 6

    if not backup_id or any(ch not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_" for ch in backup_id):
        print("Restore not started: invalid backup identifier.", file=sys.stderr)
        return 2

    print(f"{1 + step_offset}/{total_steps} Checking that no backup is currently running...", flush=True)
    lock = run(
        [*base, "run", "--rm", "--no-deps", "--entrypoint", "sh", "backup-agent", "-c",
         "test ! -f /backups/.maintenance-lock"],
        capture=True,
        check=False,
    )
    if lock.returncode:
        print("Restore not started: a backup is currently running. Wait for it to finish first.", file=sys.stderr)
        return 2

    print(f"{2 + step_offset}/{total_steps} Validating the selected recovery bundle...", flush=True)
    validated = run(
        [*base, "run", "--rm", "--no-deps", "backup-agent", "validate", "--id", backup_id],
        capture=True,
        check=False,
    )
    if validated.returncode:
        detail = (validated.stderr or validated.stdout or "").strip()
        print("Restore not started: the selected backup failed validation.", file=sys.stderr)
        if detail:
            print(detail, file=sys.stderr)
        return 2

    validation = parse_last_json(validated.stdout)
    if validation.get("valid") is not True:
        print("Restore not started: validation did not confirm a usable bundle.", file=sys.stderr)
        return 2

    running = run([*base, "ps", "-q", "makervault"], capture=True, check=False)
    replacing_existing = bool((running.stdout or "").strip())

    if not args.yes:
        print()
        print("This will replace MakerVault's current database, media and encryption-key storage.")
        if replacing_existing:
            print("A fresh safety backup will be created automatically before anything is replaced.")
        else:
            print("No running MakerVault app was detected; this looks like a clean recovery target.")
        typed = input(f"Type the backup ID to continue ({backup_id}): ").strip()
        if typed != backup_id:
            print("Restore cancelled; nothing was changed.")
            return 0

    print(f"{3 + step_offset}/{total_steps} Stopping the backup service and MakerVault...", flush=True)
    run([*base, "stop", "backup-agent", "makervault"], check=False)

    pre_restore_id = ""
    if replacing_existing:
        pre_restore_id = "pre-restore-" + time.strftime("%Y%m%d-%H%M%S", time.gmtime())
        print(f"{4 + step_offset}/{total_steps} Creating a pre-restore safety backup...", flush=True)
        safety = run(
            [*base, "run", "--rm", "--no-deps", "backup-agent", "backup", "--id", pre_restore_id, "--label", "Automatic pre-restore safety backup"],
            capture=True,
            check=False,
        )
        if safety.returncode:
            print("Safety backup failed. The requested restore was NOT started.", file=sys.stderr)
            detail = (safety.stderr or safety.stdout or "").strip()
            if detail:
                print(detail, file=sys.stderr)
            run([*base, "up", "-d", "makervault", "backup-agent"], check=False)
            return 3
        print(f"Safety backup created: {pre_restore_id}", flush=True)
    else:
        print(f"{4 + step_offset}/{total_steps} Clean target confirmed; no pre-restore data exists to protect.", flush=True)

    print(f"{5 + step_offset}/{total_steps} Restoring database, media and encryption keys...", flush=True)
    restored = run(
        [*base, "run", "--rm", "--no-deps", "--user", "0:0", "backup-agent", "restore", "--id", backup_id],
        capture=True,
        check=False,
    )
    if restored.returncode:
        print("Restore failed after validation.", file=sys.stderr)
        if replacing_existing:
            print(f"MakerVault has been left stopped to avoid starting against a partial restore. Safety backup: {pre_restore_id}", file=sys.stderr)
            print(
                "Recovery command: "
                + " ".join([*base, "run", "--rm", "--no-deps", "--user", "0:0", "backup-agent", "restore", "--id", pre_restore_id]),
                file=sys.stderr,
            )
        detail = (restored.stderr or restored.stdout or "").strip()
        if detail:
            print(detail, file=sys.stderr)
        return 4

    print(f"{6 + step_offset}/{total_steps} Starting MakerVault and its backup service...", flush=True)
    run([*base, "up", "-d", "--build", "makervault", "backup-agent"])
    run([*base, "ps"], check=False)
    print()
    print(f"Restore complete from {backup_id}.")
    if pre_restore_id:
        print(f"Pre-restore safety backup retained as {pre_restore_id}.")
    print("Open MakerVault and verify a known project, inventory item and private file before deleting any recovery bundle.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
