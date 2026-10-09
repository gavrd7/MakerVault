#!/usr/bin/env python3
"""Guarded MakerVault restore helper for the standard Docker Compose deployment."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import ipaddress
import socket
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


def _env_values(text: str) -> dict[str, str]:
    values = {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def detect_recovery_hosts() -> list[str]:
    """Return likely host IPv4 addresses for direct access to a replacement server."""
    candidates = []

    # Ask the kernel which source address it would use for an ordinary routed
    # connection. UDP connect does not send a packet.
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.connect(("192.0.2.1", 9))
            candidates.append(sock.getsockname()[0])
    except OSError:
        pass

    # Include additional host addresses as a fallback for multi-homed/LAN-only hosts.
    result = run(["hostname", "-I"], capture=True, check=False)
    if result.returncode == 0:
        candidates.extend((result.stdout or "").split())

    hosts = []
    for candidate in candidates:
        try:
            address = ipaddress.ip_address(candidate)
        except ValueError:
            continue
        if (
            address.version != 4
            or address.is_loopback
            or address.is_link_local
            or address.is_multicast
            or address.is_unspecified
        ):
            continue
        value = str(address)
        if value not in hosts:
            hosts.append(value)
    return hosts


def adapt_recovered_env_for_hosts(path: Path, hosts: list[str]) -> list[str]:
    """Append replacement-host access values without deleting restored settings."""
    clean_hosts = []
    for host in hosts:
        try:
            address = ipaddress.ip_address(host)
        except ValueError as exc:
            raise RestoreError(f"Invalid recovery host address: {host}") from exc
        if address.version != 4 or address.is_loopback or address.is_unspecified:
            raise RestoreError(f"Recovery host must be a non-loopback IPv4 address: {host}")
        value = str(address)
        if value not in clean_hosts:
            clean_hosts.append(value)

    if not clean_hosts:
        return []

    text = path.read_text(encoding="utf-8")
    values = _env_values(text)
    try:
        port = int(values.get("MAKERVAULT_PORT", "8765"))
    except ValueError as exc:
        raise RestoreError("MAKERVAULT_PORT in the recovered .env must be numeric.") from exc
    if not 1 <= port <= 65535:
        raise RestoreError("MAKERVAULT_PORT in the recovered .env is outside 1-65535.")

    origins = [f"http://{host}:{port}" for host in clean_hosts]
    https_enabled = values.get("MAKERVAULT_HTTPS_ENABLED", "false").strip().lower() in {"1", "true", "yes", "on"}
    if https_enabled:
        try:
            https_port = int(values.get("MAKERVAULT_HTTPS_PORT", "8443"))
        except ValueError as exc:
            raise RestoreError("MAKERVAULT_HTTPS_PORT in the recovered .env must be numeric.") from exc
        if not 1 <= https_port <= 65535:
            raise RestoreError("MAKERVAULT_HTTPS_PORT in the recovered .env is outside 1-65535.")
        origins.extend(f"https://{host}:{https_port}" for host in clean_hosts)

    additions = {
        "DJANGO_ALLOWED_HOSTS": clean_hosts,
        "DJANGO_CSRF_TRUSTED_ORIGINS": origins,
    }
    if values.get("MAKERVAULT_HTTPS_SELF_SIGNED", "false").strip().lower() in {"1", "true", "yes", "on"}:
        additions["MAKERVAULT_HTTPS_SELF_SIGNED_NAMES"] = clean_hosts

    lines = text.splitlines()
    for key, new_values in additions.items():
        existing = [value.strip() for value in values.get(key, "").split(",") if value.strip()]
        merged = existing[:]
        for value in new_values:
            if value not in merged:
                merged.append(value)
        replacement = f"{key}={','.join(merged)}"
        replaced = False
        for index, raw in enumerate(lines):
            stripped = raw.strip()
            if stripped and not stripped.startswith("#") and stripped.split("=", 1)[0].strip() == key:
                lines[index] = replacement
                replaced = True
                break
        if not replaced:
            lines.append(replacement)

    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    os.chmod(path, 0o600)
    return clean_hosts


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
    parser.add_argument("--build-override", action="store_true", help="Include compose.build.yaml for locally built development deployments.")
    parser.add_argument("--yes", action="store_true", help="Skip the interactive backup-ID confirmation.")
    parser.add_argument(
        "--recovery-host",
        action="append",
        default=[],
        help="IPv4 address to add to allowed hosts/origins on a clean off-server restore. May be repeated; otherwise MakerVault auto-detects the replacement host.",
    )
    parser.add_argument("--source-dir", default=str(Path(__file__).resolve().parent.parent))
    args = parser.parse_args()

    source = Path(args.source_dir).resolve()
    compose_names = ("compose.yaml", "compose.yml", "docker-compose.yaml", "docker-compose.yml")
    present = [source / name for name in compose_names if (source / name).is_file()]
    if not present:
        print("Restore not started: no Compose file found (compose.yaml, compose.yml, docker-compose.yaml, docker-compose.yml).", file=sys.stderr)
        return 2
    # Match Docker Compose's preference for the canonical compose.yaml name.
    # Print the selected file so ambiguous deployments are visible to operators.
    compose_file = present[0]
    if len(present) > 1:
        print("Multiple Compose files found; selecting " + compose_file.name + ".")
    else:
        print("Using Compose file: " + compose_file.name)

    docker = compose_command(args.sudo)
    base = [*docker, "-f", str(compose_file)]
    if args.build_override:
        override = source / "compose.build.yaml"
        if not override.is_file():
            print("Restore not started: compose.build.yaml was not found.", file=sys.stderr)
            return 2
        base.extend(["-f", str(override)])
    base.extend(["--project-directory", str(source)])
    env_file = source / ".env"

    bundle = Path(args.bundle).expanduser().resolve() if args.bundle else None
    recovered_env = False
    if bundle:
        print("1/8 Verifying the off-server recovery bundle...", flush=True)
        try:
            bundled_env = inspect_local_bundle(bundle)
        except RestoreError as exc:
            print(f"Restore not started: {exc}", file=sys.stderr)
            return 2

        if not env_file.exists():
            recovered_env = True
            if not bundled_env:
                print("Restore not started: the clean checkout has no .env and the bundle does not contain one.", file=sys.stderr)
                return 2
            env_file.write_bytes(bundled_env)
            os.chmod(env_file, 0o600)
            print("Recovered .env from the verified bundle because this checkout did not have one.", flush=True)
            try:
                recovery_hosts = args.recovery_host or detect_recovery_hosts()
                added_hosts = adapt_recovered_env_for_hosts(env_file, recovery_hosts)
            except RestoreError as exc:
                print(f"Restore not started: could not adapt recovered host settings: {exc}", file=sys.stderr)
                return 2
            if added_hosts:
                print(
                    "Added replacement-host access to recovered .env: "
                    + ", ".join(added_hosts)
                    + " (existing allowed hosts/origins were preserved).",
                    flush=True,
                )
            else:
                print(
                    "No replacement-host IPv4 address could be detected. Review DJANGO_ALLOWED_HOSTS "
                    "and DJANGO_CSRF_TRUSTED_ORIGINS before opening MakerVault, or rerun with --recovery-host.",
                    flush=True,
                )
        else:
            print("Existing .env retained. The restore helper never silently overwrites current deployment configuration.", flush=True)

        backup_id = "imported-" + digest_file(bundle)[:16]
        try:
            print("2/8 Preparing the MakerVault image and database...", flush=True)
            run([*base, "build", "makervault"])
            run([*base, "up", "-d", "--wait", "postgres", "redis"])
            stage = [
                *base, "run", "--rm", "--no-deps", "-T",
                "--entrypoint", "sh", "makervault", "-c",
                'umask 077; mkdir -p /app/backups; cat > "/app/backups/$1.mvbackup"; chmod 600 "/app/backups/$1.mvbackup"',
                "sh", backup_id,
            ]
            stream_file(stage, bundle)
            registered = run(
                [*base, "run", "--rm", "--no-deps", "--entrypoint", "python", "makervault",
                 "manage.py", "backup_bundle", "register", "--id", backup_id],
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

    if not bundle:
        try:
            run([*base, "build", "makervault"])
        except RestoreError as exc:
            print(f"Restore not started: could not prepare the MakerVault image: {exc}", file=sys.stderr)
            return 2

    print(f"{1 + step_offset}/{total_steps} Checking that no backup is currently running...", flush=True)
    lock = run(
        [*base, "run", "--rm", "--no-deps", "--entrypoint", "sh", "makervault", "-c",
         "test ! -f /app/backups/.maintenance-lock"],
        capture=True,
        check=False,
    )
    if lock.returncode:
        print("Restore not started: a backup is currently running. Wait for it to finish first.", file=sys.stderr)
        return 2

    print(f"{2 + step_offset}/{total_steps} Validating the selected recovery bundle...", flush=True)
    validated = run(
        [*base, "run", "--rm", "--no-deps", "--entrypoint", "python", "makervault",
         "manage.py", "backup_bundle", "validate", "--id", backup_id],
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

    print(f"{3 + step_offset}/{total_steps} Stopping MakerVault...", flush=True)
    run([*base, "stop", "makervault"], check=False)

    pre_restore_id = ""
    if replacing_existing:
        pre_restore_id = "pre-restore-" + time.strftime("%Y%m%d-%H%M%S", time.gmtime())
        print(f"{4 + step_offset}/{total_steps} Creating a pre-restore safety backup...", flush=True)
        safety = run(
            [*base, "run", "--rm", "--no-deps", "--entrypoint", "python", "makervault",
             "manage.py", "backup_bundle", "create", "--id", pre_restore_id,
             "--label", "Automatic pre-restore safety backup"],
            capture=True,
            check=False,
        )
        if safety.returncode:
            print("Safety backup failed. The requested restore was NOT started.", file=sys.stderr)
            detail = (safety.stderr or safety.stdout or "").strip()
            if detail:
                print(detail, file=sys.stderr)
            run([*base, "up", "-d", "makervault"], check=False)
            return 3
        print(f"Safety backup created: {pre_restore_id}", flush=True)
    else:
        print(f"{4 + step_offset}/{total_steps} Clean target confirmed; no pre-restore data exists to protect.", flush=True)

    print(f"{5 + step_offset}/{total_steps} Restoring database, media and encryption keys...", flush=True)
    restored = run(
        [*base, "run", "--rm", "--no-deps", "--entrypoint", "python", "makervault",
         "manage.py", "backup_bundle", "restore", "--id", backup_id],
        capture=True,
        check=False,
    )
    if restored.returncode:
        print("Restore failed after validation.", file=sys.stderr)
        if replacing_existing:
            print(f"MakerVault has been left stopped to avoid starting against a partial restore. Safety backup: {pre_restore_id}", file=sys.stderr)
            print(
                "Recovery command: "
                + " ".join([*base, "run", "--rm", "--no-deps", "--entrypoint", "python", "makervault",
                            "manage.py", "backup_bundle", "restore", "--id", pre_restore_id]),
                file=sys.stderr,
            )
        detail = (restored.stderr or restored.stdout or "").strip()
        if detail:
            print(detail, file=sys.stderr)
        return 4

    if bundle and recovered_env:
        values = _env_values(env_file.read_text(encoding="utf-8"))
        self_signed = values.get("MAKERVAULT_HTTPS_SELF_SIGNED", "false").strip().lower() in {"1", "true", "yes", "on"}
        https_enabled = values.get("MAKERVAULT_HTTPS_ENABLED", "false").strip().lower() in {"1", "true", "yes", "on"}
        if self_signed and https_enabled:
            print("Refreshing MakerVault-managed self-signed certificate for the replacement host...", flush=True)
            cleared = run(
                [
                    *base, "run", "--rm", "--no-deps", "-T",
                    "--entrypoint", "sh", "makervault", "-c",
                    'rm -f "$MAKERVAULT_TLS_CERT_FILE" "$MAKERVAULT_TLS_KEY_FILE"',
                ],
                capture=True,
                check=False,
            )
            if cleared.returncode:
                detail = (cleared.stderr or cleared.stdout or "").strip()
                print(
                    "Restore completed but the replacement-host self-signed certificate could not be refreshed. "
                    "MakerVault has been left stopped; review TLS storage before starting it.",
                    file=sys.stderr,
                )
                if detail:
                    print(detail, file=sys.stderr)
                return 5

    print(f"{6 + step_offset}/{total_steps} Starting MakerVault...", flush=True)
    run([*base, "up", "-d", "--build", "makervault"])
    run([*base, "ps"], check=False)
    print()
    print(f"Restore complete from {backup_id}.")
    if pre_restore_id:
        print(f"Pre-restore safety backup retained as {pre_restore_id}.")
    print("Open MakerVault and verify a known project, inventory item and private file before deleting any recovery bundle.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
