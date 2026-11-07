"""Static, administrator-approved per-engine inventory for one isolated worker.

All entries must be supplied by the administrator through a pinned deployment.
No discovery, PATH lookup, package installation or network downloads happen here.
"""
import hashlib
import json
import os
from pathlib import Path
from functools import lru_cache

SUPPORTED = frozenset({"orcaslicer", "crealityprint", "prusaslicer"})


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
    raw = os.environ.get("SLICER_ENGINES_JSON", "")
    if raw:
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
        path = Path(binary)
        if not path.is_absolute() or path.is_symlink() or not path.is_file() or not os.access(path, os.X_OK):
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
