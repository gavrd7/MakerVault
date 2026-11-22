"""Static, administrator-approved per-engine inventory for one isolated worker.

All entries must be supplied by the administrator through a pinned deployment.
No discovery, PATH lookup, package installation or network downloads happen here.
"""
import hashlib
import json
import os
import re
from pathlib import Path
from functools import lru_cache

SUPPORTED = frozenset({"orcaslicer", "crealityprint", "prusaslicer", "bambustudio"})
# Reviewed, exact native AppRun hash of the pinned official 02.09.01.70 build.
# This is distinct from the upstream AppImage SHA-256.
BAMBU_VERSION = "02.09.01.70"
BAMBU_RUNTIME_SHA256 = "eaf5a1c6ff4f0d49d6e0c0bacf106309daa2c822ca1ebe8739067699e6cdaef4"

# The host-side installer owns this read-only, volume-backed registry. The
# worker never writes to it or downloads/installs executables.
ENGINE_STORE = Path("/opt/engine-store")
ACTIVE_MANIFEST = ENGINE_STORE / "active.json"
MAX_MANIFEST_BYTES = 16 * 1024


def _read_active_manifest():
    """Return explicitly approved engine selections from the persistent volume.

    If the file does not exist, retain the existing image-bundled registry.
    Invalid manifests MUST fail closed rather than falling back to a possibly
    stale environment approval.
    """
    if not ACTIVE_MANIFEST.exists() and not ACTIVE_MANIFEST.is_symlink():
        return None
    if ACTIVE_MANIFEST.is_symlink() or not ACTIVE_MANIFEST.is_file():
        raise ValueError("Invalid active engine manifest.")
    if not 0 < ACTIVE_MANIFEST.stat().st_size <= MAX_MANIFEST_BYTES:
        raise ValueError("Engine manifest exceeds size limit.")
    doc = json.loads(ACTIVE_MANIFEST.read_text(encoding="utf-8"))
    if (not isinstance(doc, dict) or set(doc) != {"schema_version", "engines"}
            or type(doc["schema_version"]) is not int or doc["schema_version"] != 1 or not isinstance(doc["engines"], dict)
            or len(doc["engines"]) > len(SUPPORTED)):
        raise ValueError("Invalid engine manifest schema.")
    return doc["engines"]


def _valid_store_path(path, key, version):
    """Approved binary must be inside its exact engine/version installation."""
    if not path.is_absolute() or not path.is_file():
        return False
    # Reject traversal and symlinked engine/version parent directories.
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._+-]{0,79}", version) or version in {".", ".."}:
        return False
    base = ENGINE_STORE / "versions" / key / version
    if any(node.is_symlink() for node in (ENGINE_STORE, ENGINE_STORE / "versions",
                                         ENGINE_STORE / "versions" / key, base)):
        return False
    try:
        canonical_base = base.resolve(strict=True)
        canonical = path.resolve(strict=True)
        # Only the AppImage's own AppRun entrypoint may be a symlink, and
        # its final target must remain inside this exact engine version.
        if path.is_symlink() and path.name != "AppRun":
            return False
        return canonical.is_relative_to(canonical_base)
    except (OSError, ValueError):
        return False



@lru_cache(maxsize=32)
def _hash_binary(path, size, mtime_ns, inode):
    digest = hashlib.sha256()
    with open(path, "rb") as source:
        while chunk := source.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def configured_engines():
    if os.environ.get("SLICER_WORKER_ENABLED") != "1":
        return {}
    token = os.environ.get("SLICER_WORKER_TOKEN", "")
    if len(token) < 32:
        return {}
    try:
        stored = _read_active_manifest()
    except (ValueError, OSError, UnicodeError):
        return {}
    raw = os.environ.get("SLICER_ENGINES_JSON", "") if stored is None else ""
    if stored is not None:
        entries = stored
        if not entries or set(entries) - SUPPORTED:
            return {}
    elif raw:
        try:
            entries = json.loads(raw)
        except (ValueError, TypeError):
            return {}
        if not isinstance(entries, dict) or not entries or set(entries) - SUPPORTED:
            return {}
    else:
        # Compatibility: older approved single-engine images.
        entries = {
            os.environ.get("SLICER_ENGINE", "orcaslicer"): {
                "binary": os.environ.get("SLICER_ENGINE_BINARY", ""),
                "version": os.environ.get("SLICER_ENGINE_VERSION", ""),
                "binary_sha256": os.environ.get("SLICER_ENGINE_BINARY_SHA256", ""),
            },
        }
    result = {}
    for key, entry in entries.items():
        if key not in SUPPORTED or not isinstance(entry, dict) or set(entry) != {
            "binary", "version", "binary_sha256"
        }:
            continue
        binary, version, digest = entry["binary"], entry["version"], entry["binary_sha256"]
        if not isinstance(binary, str) or not isinstance(version, str) or not 1 <= len(version) <= 80:
            continue
        if not isinstance(digest, str) or len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest):
            continue
        if key == "bambustudio" and (version != BAMBU_VERSION
                or digest != BAMBU_RUNTIME_SHA256):
            continue
        path = Path(binary)
        if (not path.is_absolute() or not path.is_file()
                or (path.is_symlink() and stored is None)
                or not os.access(path, os.X_OK)
                or (stored is not None and not _valid_store_path(path, key, version))):
            continue
        try:
            stat = path.stat()
            if not 0 < stat.st_size <= 1024 * 1024 * 1024:
                continue
            if _hash_binary(str(path), stat.st_size, stat.st_mtime_ns, stat.st_ino) != digest:
                continue
        except (OSError, ValueError):
            continue
        result[key] = {"engine": key, "binary": path, "version": version,
                       "binary_sha256": digest, "token": token}
    return result
