"""Describe an isolated, source-pinned PrusaSlicer runtime candidate.

Produces evidence for human review, NOT an installer approval or signature.
Only the opt-in Prusa candidate build calls this script.
"""
import argparse
import hashlib
import json
from pathlib import Path
import stat

SOURCE_COMMIT = "450d70dd81c9b8990bc6bc8e690e31f82ddceb11"
SOURCE_TAG = "version_2.9.7"
MAX_FILES = 20000
MAX_TOTAL = 1024 * 1024 * 1024


def digest(path):
    value = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()


def manifest(root):
    root = Path(root).resolve(strict=True)
    if not root.is_dir():
        raise ValueError("Prusa candidate is not a directory")
    required = {"bin/prusa-slicer", "resources/profiles/PrusaResearch.ini", "LICENSE"}
    found = set()
    files = []
    total = 0
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root).as_posix()
        if path.is_symlink():
            raise ValueError("Prusa candidate contains a symlink")
        mode = path.lstat().st_mode
        if stat.S_ISDIR(mode):
            continue
        if not stat.S_ISREG(mode):
            raise ValueError("Prusa candidate contains a special file")
        size = path.stat().st_size
        if size < 1 or size > MAX_TOTAL:
            raise ValueError("Prusa candidate contains an invalid file")
        total += size
        if total > MAX_TOTAL or len(files) >= MAX_FILES:
            raise ValueError("Prusa candidate exceeds bounds")
        files.append({"path": relative, "size": size, "sha256": digest(path)})
        found.add(relative)
    if not required.issubset(found):
        raise ValueError("Prusa candidate is missing runtime, profiles or licence")
    executable = root / "bin/prusa-slicer"
    if not executable.stat().st_mode & stat.S_IXUSR:
        raise ValueError("Prusa candidate executable is not executable")
    with executable.open("rb") as binary:
        if binary.read(4) != b"\x7fELF":
            raise ValueError("Prusa candidate binary is not ELF")
    return {"schema": 1, "engine": "prusaslicer", "version": "2.9.7",
            "platform": "linux/amd64", "source_tag": SOURCE_TAG,
            "source_commit": SOURCE_COMMIT, "file_count": len(files),
            "total_bytes": total, "files": files,
            "install_approved": False}


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--root", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    args = p.parse_args()
    result = manifest(args.root)
    destination = args.output
    if destination.exists() or destination.is_symlink():
        raise ValueError("Manifest output must not already exist")
    destination.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(f"Review-only Prusa candidate: {result['file_count']} files, {result['total_bytes']} bytes")


if __name__ == "__main__":
    main()
