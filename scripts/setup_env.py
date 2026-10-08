#!/usr/bin/env python3
"""Safely initialize MakerVault's .env and its two required application secrets."""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import secrets
import tempfile

PLACEHOLDERS = {
    "DJANGO_SECRET_KEY": {"", "CHANGE_ME_TO_A_LONG_RANDOM_VALUE"},
    "POSTGRES_PASSWORD": {"", "CHANGE_ME_DATABASE_PASSWORD"},
}


def setup_env(destination: Path, template: Path) -> list[str]:
    if destination.is_symlink():
        raise ValueError(f"Refusing to modify a symbolic link: {destination}")
    if not destination.exists() and not template.is_file():
        raise FileNotFoundError(f"Environment template not found: {template}")

    source = destination if destination.exists() else template
    if not source.is_file():
        raise ValueError(f"Not a regular file: {source}")
    text = source.read_text(encoding="utf-8")
    lines = text.splitlines(keepends=True)
    found: set[str] = set()
    generated: list[str] = []
    rewritten: list[str] = []

    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in line:
            rewritten.append(line)
            continue
        key, value = line.split("=", 1)
        name = key.strip()
        if name not in PLACEHOLDERS:
            rewritten.append(line)
            continue
        if name in found:
            raise ValueError(f"Duplicate setting {name} in {source}; resolve this before setup.")
        found.add(name)
        actual = value.strip().strip("\\r\\n").strip("'\\\"")
        if actual in PLACEHOLDERS[name]:
            generated.append(name)
            newline = "\\n" if line.endswith("\\n") else ""
            rewritten.append(f"{name}={secrets.token_urlsafe(64)}{newline}")
        else:
            rewritten.append(line)

    for name in PLACEHOLDERS:
        if name not in found:
            if rewritten and not rewritten[-1].endswith("\\n"):
                rewritten.append("\\n")
            rewritten.append(f"{name}={secrets.token_urlsafe(64)}\\n")
            generated.append(name)

    original_mode = destination.stat().st_mode & 0o777 if destination.exists() else 0o600
    mode = original_mode & 0o600
    if not mode & 0o400:
        mode |= 0o400
    fd, tmp_path = tempfile.mkstemp(prefix=".env.", dir=destination.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as handle:
            handle.writelines(rewritten)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(tmp_path, mode)
        os.replace(tmp_path, destination)
    finally:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)
    return generated


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env", type=Path, default=Path(".env"), help="Output file (default: .env)")
    parser.add_argument("--template", type=Path, default=Path(".env.example"), help="Source template")
    args = parser.parse_args()
    changed = setup_env(args.env, args.template)
    if changed:
        print(f"Environment ready: {args.env} (generated: {', '.join(changed)}).")
    else:
        print(f"Environment ready: {args.env} (existing secrets preserved).")
    print("Review port, hostname and storage settings before starting Docker Compose.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
