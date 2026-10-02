#!/usr/bin/env python3
"""Guarded MakerVault restore helper for the standard Docker Compose deployment."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess
import sys
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
            detail = (result.stderr or result.stdout or "").strip().splitlines()
            detail = detail[-1] if detail else ""
        raise RestoreError(detail or f"Command failed: {' '.join(command)}")
    return result


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


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Safely restore one MakerVault recovery bundle with an automatic pre-restore backup."
    )
    parser.add_argument("--backup-id", required=True, help="Backup identifier shown in MakerVault Settings > Backup & restore.")
    parser.add_argument("--sudo", action="store_true", help="Run Docker commands through sudo.")
    parser.add_argument("--yes", action="store_true", help="Skip the interactive backup-ID confirmation.")
    parser.add_argument("--source-dir", default=str(Path(__file__).resolve().parent.parent))
    args = parser.parse_args()

    source = Path(args.source_dir).resolve()
    if not (source / "compose.yaml").is_file():
        print("Restore not started: compose.yaml was not found in the MakerVault checkout.", file=sys.stderr)
        return 2

    backup_id = args.backup_id.strip()
    if not backup_id or any(ch not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_" for ch in backup_id):
        print("Restore not started: invalid backup identifier.", file=sys.stderr)
        return 2

    docker = compose_command(args.sudo)
    base = [*docker, "-f", str(source / "compose.yaml"), "--project-directory", str(source)]

    print("1/6 Checking that no backup is currently running...", flush=True)
    lock = run(
        [*base, "run", "--rm", "--no-deps", "--entrypoint", "sh", "backup-agent", "-c",
         "test ! -f /backups/.maintenance-lock"],
        capture=True,
        check=False,
    )
    if lock.returncode:
        print("Restore not started: a backup is currently running. Wait for it to finish first.", file=sys.stderr)
        return 2

    print("2/6 Validating the selected recovery bundle...", flush=True)
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

    if not args.yes:
        print()
        print("This will replace MakerVault's current database, media and encryption-key storage.")
        print("A fresh safety backup will be created automatically before anything is replaced.")
        typed = input(f"Type the backup ID to continue ({backup_id}): ").strip()
        if typed != backup_id:
            print("Restore cancelled; nothing was changed.")
            return 0

    print("3/6 Stopping the backup service and MakerVault...", flush=True)
    run([*base, "stop", "backup-agent", "makervault"])

    pre_restore_id = "pre-restore-" + time.strftime("%Y%m%d-%H%M%S", time.gmtime())
    print("4/6 Creating a pre-restore safety backup...", flush=True)
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
        run([*base, "start", "makervault", "backup-agent"], check=False)
        return 3

    print(f"Safety backup created: {pre_restore_id}", flush=True)
    print("5/6 Restoring database, media and encryption keys...", flush=True)
    restored = run(
        [*base, "run", "--rm", "--no-deps", "backup-agent", "restore", "--id", backup_id],
        capture=True,
        check=False,
    )
    if restored.returncode:
        print("Restore failed after the safety backup was created.", file=sys.stderr)
        print(f"MakerVault has been left stopped to avoid starting against a partial restore. Safety backup: {pre_restore_id}", file=sys.stderr)
        detail = (restored.stderr or restored.stdout or "").strip()
        if detail:
            print(detail, file=sys.stderr)
        print(f"Recovery command: {' '.join(docker)} compose run --rm --no-deps backup-agent restore --id {pre_restore_id}", file=sys.stderr)
        return 4

    print("6/6 Starting MakerVault and its backup service...", flush=True)
    run([*base, "start", "makervault", "backup-agent"])
    run([*base, "ps"], check=False)
    print()
    print(f"Restore complete from {backup_id}.")
    print(f"Pre-restore safety backup retained as {pre_restore_id}.")
    print("Open MakerVault and verify a known project, inventory item and private file before deleting any recovery bundle.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
