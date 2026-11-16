"""Host-admin-only persistent engine store bootstrap for ONE slicer-worker.

Run in a disposable Docker maintenance container with the engine volume
mounted read-write; never in the MakerVault web app or live worker.
No downloads, shell commands, Docker socket, or background updates.

The initial approved engine is the exact checksum-reviewed Orca 2.5.0
bundled in the immutable bootstrap image. Later engines can use the same
versioned storage scheme once a separately audited installer exists.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import sys
import tempfile

from .engine_registry import ENGINE_STORE, SUPPORTED

SOURCE = Path("/opt/engines")
EXPECTED_ORCA_SHA = "b30b0ae933e653692cf85a493287a949215ae4c14d547a00203d16dfcadb8054"
APPROVAL_VERSION = "2.5.0"
VERSION_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._+-]{0,79}$")


def _sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while chunk := source.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _manifest(store):
    path = store / "active.json"
    if not path.exists():
        return {"schema_version": 1, "engines": {}}
    if path.is_symlink() or not path.is_file() or path.stat().st_size > 16384:
        raise ValueError("Invalid persistent active engine registry.")
    data = json.loads(path.read_text(encoding="utf-8"))
    if (not isinstance(data, dict) or set(data) != {"schema_version", "engines"}
            or data["schema_version"] != 1 or not isinstance(data["engines"], dict)
            or set(data["engines"]) - SUPPORTED):
        raise ValueError("Invalid persistent engine manifest schema.")
    return data


def _write(store, payload):
    store.mkdir(parents=True, exist_ok=True)
    fd, filename = tempfile.mkstemp(prefix=".active-", suffix=".tmp", dir=store)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as target:
            json.dump(payload, target, separators=(",", ":"), sort_keys=True)
            target.write("\n")
            target.flush()
            os.fsync(target.fileno())
        os.chmod(filename, 0o644)
        os.replace(filename, store / "active.json")
    finally:
        if os.path.exists(filename):
            os.unlink(filename)


def seed_bundled_orca(store=ENGINE_STORE, source=SOURCE):
    """Copy the known-good reviewed bundled engine into one versioned volume."""
    src = source / "orcaslicer.AppImage"
    appdir = source / "squashfs-root"
    if (src.is_symlink() or not src.is_file() or appdir.is_symlink()
            or not (appdir / "AppRun").is_file()):
        raise ValueError("Approved bundled Orca runtime is missing.")
    if _sha256(src) != EXPECTED_ORCA_SHA:
        raise ValueError("Bundled Orca digest does not match reviewed release.")
    base = store / "versions" / "orcaslicer"
    base.mkdir(parents=True, exist_ok=True)
    target = base / APPROVAL_VERSION
    if target.exists() or target.is_symlink():
        raise ValueError("Engine version already exists. Never overwrite an installed binary.")
    stage = Path(tempfile.mkdtemp(prefix=".install-", dir=base))
    try:
        shutil.copy2(src, stage / src.name)
        shutil.copytree(appdir, stage / "squashfs-root", symlinks=True)
        if _sha256(stage / src.name) != EXPECTED_ORCA_SHA:
            raise ValueError("Copied Orca checksum does not match approved release.")
        if not (stage / "squashfs-root" / "AppRun").is_file():
            raise ValueError("Copied Orca runtime is incomplete.")
        os.chmod(stage / src.name, 0o555)
        os.chmod(stage, 0o755)
        os.rename(stage, target)
    finally:
        if stage.exists():
            shutil.rmtree(stage)
    return target


def activate(store, *, engine, version, sha256):
    """Activate one already-installed, independently verified engine version."""
    if engine not in SUPPORTED or not VERSION_RE.fullmatch(version) or version in {".", ".."}:
        raise ValueError("Unsupported engine or version.")
    if not re.fullmatch(r"[a-f0-9]{64}", sha256):
        raise ValueError("Exact approved binary digest is required.")
    root = store / "versions" / engine / version
    binary = root / (engine + ".AppImage")
    if (root.is_symlink() or binary.is_symlink() or not binary.is_file()
            or _sha256(binary) != sha256):
        raise ValueError("Installed engine is missing or its checksum is not approved.")
    if engine == "orcaslicer" and not (root / "squashfs-root" / "AppRun").is_file():
        raise ValueError("Installed Orca runtime is missing.")
    current = _manifest(store)
    updated = {"schema_version": 1, "engines": {**current["engines"]}}
    updated["engines"][engine] = {
        "binary": str(binary), "version": version, "binary_sha256": sha256,
    }
    previous = store / "previous.json"
    # Preserve one rollback snapshot; never mutate or delete installed versions.
    if current["engines"]:
        with previous.open("w", encoding="utf-8") as target:
            json.dump(current, target, separators=(",", ":"), sort_keys=True)
            target.write("\n")
    _write(store, updated)
    return updated


def rollback(store):
    """Restore previous active selection; both versions remain on disk."""
    previous = store / "previous.json"
    if previous.is_symlink() or not previous.is_file():
        raise ValueError("No previously approved engine selection to restore.")
    data = json.loads(previous.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or data.get("schema_version") != 1 or not isinstance(data.get("engines"), dict):
        raise ValueError("Previous engine selection is invalid.")
    # Revalidate every active binary before activating a historic selection.
    for engine, row in data["engines"].items():
        if engine not in SUPPORTED or not isinstance(row, dict):
            raise ValueError("Previous engine entry is unsupported.")
        version, sha = row.get("version"), row.get("binary_sha256")
        if (not isinstance(version, str) or not VERSION_RE.fullmatch(version)
                or not isinstance(sha, str)):
            raise ValueError("Previous engine metadata is invalid.")
        binary = store / "versions" / engine / version / (engine + ".AppImage")
        if (binary.is_symlink() or not binary.is_file() or _sha256(binary) != sha):
            raise ValueError("Previously approved engine is missing or modified.")
    current = _manifest(store)
    _write(store, data)
    # Preserve ability to reverse the rollback explicitly.
    with previous.open("w", encoding="utf-8") as target:
        json.dump(current, target, separators=(",", ":"), sort_keys=True)
        target.write("\n")
    return data


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("seed-bundled-orca", "activate", "rollback", "list"))
    parser.add_argument("--store", type=Path, default=ENGINE_STORE)
    parser.add_argument("--engine", choices=sorted(SUPPORTED))
    parser.add_argument("--version")
    parser.add_argument("--sha256")
    args = parser.parse_args(argv)
    if args.store.is_symlink() or not args.store.is_dir():
        parser.error("An existing non-symlink engine volume is required.")
    try:
        if args.action == "seed-bundled-orca":
            result = {"installed": str(seed_bundled_orca(args.store))}
        elif args.action == "activate":
            if not all((args.engine, args.version, args.sha256)):
                parser.error("Activation requires --engine, --version and --sha256.")
            result = activate(args.store, engine=args.engine, version=args.version,
                              sha256=args.sha256)
        elif args.action == "rollback":
            result = rollback(args.store)
        else:
            result = _manifest(args.store)
    except (OSError, ValueError, UnicodeError, json.JSONDecodeError) as exc:
        parser.exit(1, "Engine store refused operation: " + str(exc) + "\n")
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
