"""Safe installed-version inventory, activation and uninstall for the host installer.

Never accept arbitrary filesystem paths from the browser. Existing versions
stay intact on activation; uninstall explicitly removes only that engine's
version directory after updating the active manifest. No printer dispatch.
"""
import json
from pathlib import Path
import re
import shutil

from .engine_registry import SUPPORTED
from .engine_store_admin import _manifest, _sha256, _write

VERSION_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._+-]{0,79}$")
HEX = re.compile(r"^[a-f0-9]{64}$")
IDENTITY = "approved-identity.json"


def _engine_root(store, engine):
    if engine not in SUPPORTED:
        raise ValueError("Unsupported engine.")
    store = Path(store)
    root = store / "versions" / engine
    if any(path.is_symlink() for path in (store, store / "versions", root)):
        raise ValueError("Unsafe engine store directory.")
    return root


def _approved_versions(store, engine):
    """Return only versions with trusted, recorded runtime SHA-256."""
    root = _engine_root(store, engine)
    active = _manifest(store)["engines"].get(engine)
    previous_file = Path(store) / "previous.json"
    previous = None
    if previous_file.is_file() and not previous_file.is_symlink() and previous_file.stat().st_size <= 16384:
        try:
            data = json.loads(previous_file.read_text(encoding="utf-8"))
            if data.get("schema_version") == 1 and isinstance(data.get("engines"), dict):
                previous = data["engines"].get(engine)
        except (ValueError, UnicodeError, TypeError):
            pass
    results = []
    if not root.is_dir():
        return results
    for directory in root.iterdir():
        version = directory.name
        if not VERSION_RE.fullmatch(version) or version in {".", ".."} or directory.is_symlink() or not directory.is_dir():
            continue
        row = None
        identity = directory / IDENTITY
        if identity.is_file() and not identity.is_symlink() and identity.stat().st_size <= 4096:
            try:
                candidate = json.loads(identity.read_text(encoding="utf-8"))
                if (candidate.get("engine") == engine and candidate.get("version") == version
                        and set(candidate) == {"engine", "version", "binary", "binary_sha256"}):
                    row = candidate
            except (ValueError, UnicodeError, TypeError):
                pass
        if row is None:
            for known in (active, previous):
                if known and known.get("version") == version:
                    row = {"engine": engine, "version": version,
                           "binary": known.get("binary"), "binary_sha256": known.get("binary_sha256")}
                    break
        if not row or not isinstance(row.get("binary"), str) or not isinstance(row.get("binary_sha256"), str):
            continue
        binary = Path(row["binary"])
        if (not binary.is_absolute() or not HEX.fullmatch(row["binary_sha256"])
                or binary.parent == directory.parent or not binary.is_file()):
            continue
        try:
            if (not binary.resolve(strict=True).is_relative_to(directory.resolve(strict=True))
                    or (binary.is_symlink() and binary.name != "AppRun")):
                continue
        except (ValueError, OSError):
            continue
        results.append({"engine": engine, "version": version,
                        "binary_sha256": row["binary_sha256"],
                        "active": bool(active and active.get("version") == version)})
    return sorted(results, key=lambda row: row["version"], reverse=True)


def installed_versions(store):
    return {engine: _approved_versions(store, engine) for engine in sorted(SUPPORTED)}


def activate_installed(store, engine, version):
    """Switch to a previously verified version, checking the actual binary."""
    if not isinstance(version, str) or not VERSION_RE.fullmatch(version):
        raise ValueError("Invalid installed version.")
    matches = [row for row in _approved_versions(store, engine) if row["version"] == version]
    if len(matches) != 1:
        raise ValueError("Version has no verified installation identity.")
    root = _engine_root(store, engine) / version
    identity = root / IDENTITY
    current = _manifest(store)
    known = None
    if identity.is_file() and not identity.is_symlink():
        known = json.loads(identity.read_text(encoding="utf-8"))
    else:
        previous = Path(store) / "previous.json"
        if previous.is_file() and not previous.is_symlink():
            data = json.loads(previous.read_text(encoding="utf-8"))
            known = data.get("engines", {}).get(engine) if data.get("schema_version") == 1 else None
        if not known or known.get("version") != version:
            known = current["engines"].get(engine)
    if not isinstance(known, dict) or known.get("version") != version:
        raise ValueError("Installed version identity is unavailable.")
    binary = Path(known["binary"])
    digest = known["binary_sha256"]
    if (not binary.is_file() or not binary.resolve(strict=True).is_relative_to(root.resolve(strict=True))
            or _sha256(binary) != digest):
        raise ValueError("Installed version no longer matches its approved SHA-256.")
    if current["engines"].get(engine) == {"binary": str(binary), "version": version, "binary_sha256": digest}:
        raise ValueError("This engine version is already active.")
    previous = Path(store) / "previous.json"
    if current["engines"]:
        previous.write_text(json.dumps(current, separators=(",", ":")), encoding="utf-8")
    new = {"schema_version": 1, "engines": {**current["engines"],
           engine: {"binary": str(binary), "version": version, "binary_sha256": digest}}}
    _write(store, new)
    return new


def uninstall_engine(store, engine):
    """Remove only the selected engine's versions; preserve every other engine."""
    root = _engine_root(store, engine)
    if not root.is_dir():
        raise ValueError("Engine is not installed.")
    # Scan and refuse unsafe children before mutating the active selection.
    children = list(root.iterdir())
    if not children or any(child.is_symlink() or not child.is_dir()
                           or not VERSION_RE.fullmatch(child.name)
                           for child in children):
        raise ValueError("Engine installation contains unsafe files.")
    current = _manifest(store)
    if engine not in current["engines"] and not _approved_versions(store, engine):
        raise ValueError("Engine is not installed.")
    new = {"schema_version": 1, "engines": {k: v for k, v in current["engines"].items() if k != engine}}
    _write(store, new)
    # A snapshot referring to a removed version must never be restorable.
    previous = Path(store) / "previous.json"
    if previous.exists():
        if previous.is_symlink():
            raise ValueError("Unsafe engine rollback history.")
        previous.unlink()
    shutil.rmtree(root)
    return new
