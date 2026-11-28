"""Fail-closed import of the exact reviewed PrusaSlicer 2.9.7 Linux/amd64 bundle.

Only the installer container may call this code. Never use tar.extractall,
untrusted paths, runtime shells, or caller-supplied version/URL/identity.
"""
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import stat
import tarfile

VERSION = "2.9.7"
SOURCE_TAG = "version_2.9.7"
SOURCE_COMMIT = "450d70dd81c9b8990bc6bc8e690e31f82ddceb11"
RELEASE_TAG = "prusa-runtime-v2.9.7-450d70d"
ASSET_NAME = "prusa-2.9.7-headless-linux-amd64.tar.gz"
ARCHIVE_SHA256 = "963eb81fd972d50c5f8fe54c3adb6dce2eab39c9ab223534b917eae76973d913"
BINARY_SHA256 = "4488d5b6ed97c818c4c19bef58b51704726e7a20407a8eda986bc88b3b13aa18"
VENDOR_SHA256 = "a6155d92471d3b0ae11bed051bb04a4c1157fd6b05fef22416eafd12bce9c839"
ASSET_SIZE = 96094489
MAX_FILES = 20000
MAX_TOTAL = 400 * 1024 * 1024
MAX_MANIFEST = 2 * 1024 * 1024


def sha256(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as source:
        for part in iter(lambda: source.read(1024 * 1024), b""):
            h.update(part)
    return h.hexdigest()


def _checked_members(archive):
    members, names, total = [], set(), 0
    for member in archive:
        name = member.name
        path = PurePosixPath(name)
        # GNU tar includes the root directory itself before its children.
        if name in {"prusa-candidate", "prusa-candidate/"} and member.isdir():
            continue
        if (not name.startswith("prusa-candidate/") or path.is_absolute()
                or any(part in {"..", "."} for part in name.split("/"))
                or "\\" in name or len(name) > 400
                or not (member.isdir() or member.isfile())
                or member.issym() or member.islnk()):
            raise ValueError("Prusa archive contains an unsafe entry.")
        relative = PurePosixPath(*path.parts[1:])
        if not relative.parts or str(relative) in names:
            raise ValueError("Prusa archive contains a duplicate or empty path.")
        names.add(str(relative))
        if member.isfile():
            if member.size < 0 or member.size > MAX_TOTAL:
                raise ValueError("Prusa archive contains an oversized file.")
            total += member.size
        if total > MAX_TOTAL or len(names) > MAX_FILES + 2000:
            raise ValueError("Prusa archive exceeds size or file limits.")
        members.append((relative, member))
    return members


def unpack_reviewed_prusa(archive_path, destination):
    """Verify pinned tar digest and manifest before returning a trusted binary.

    destination is the installer's fresh private staging directory.
    No version is activated here; caller commits the stage atomically.
    """
    archive_path, destination = Path(archive_path), Path(destination)
    if (archive_path.is_symlink() or not archive_path.is_file()
            or archive_path.stat().st_size != ASSET_SIZE
            or sha256(archive_path) != ARCHIVE_SHA256):
        raise ValueError("Prusa archive does not match the reviewed exact release.")
    if destination.is_symlink() or not destination.is_dir() or any(destination.iterdir()):
        raise ValueError("Prusa staging directory must be fresh and private.")
    with tarfile.open(archive_path, mode="r:gz") as bundle:
        entries = _checked_members(bundle)
        for relative, member in entries:
            path = destination.joinpath(*relative.parts)
            if member.isdir():
                path.mkdir(parents=True, exist_ok=True)
            else:
                path.parent.mkdir(parents=True, exist_ok=True)
                if path.exists() or path.is_symlink():
                    raise ValueError("Prusa archive has conflicting paths.")
                stream = bundle.extractfile(member)
                if stream is None:
                    raise ValueError("Prusa archive has an unreadable file.")
                with stream, path.open("xb") as target:
                    count = 0
                    while chunk := stream.read(1024 * 1024):
                        count += len(chunk)
                        if count > member.size:
                            raise ValueError("Prusa archive file exceeded declared size.")
                        target.write(chunk)
                    if count != member.size:
                        raise ValueError("Prusa archive file was truncated.")

    manifest_file = destination / "review-manifest.json"
    if (manifest_file.is_symlink() or not manifest_file.is_file()
            or not 0 < manifest_file.stat().st_size <= MAX_MANIFEST):
        raise ValueError("Prusa review manifest missing or oversized.")
    doc = json.loads(manifest_file.read_text(encoding="utf-8"))
    if (not isinstance(doc, dict) or doc.get("schema") != 1
            or doc.get("engine") != "prusaslicer" or doc.get("version") != VERSION
            or doc.get("platform") != "linux/amd64"
            or doc.get("source_tag") != SOURCE_TAG
            or doc.get("source_commit") != SOURCE_COMMIT
            or doc.get("install_approved") is not False
            or type(doc.get("file_count")) is not int
            or type(doc.get("total_bytes")) is not int
            or not isinstance(doc.get("files"), list)):
        raise ValueError("Prusa source or manifest identity is invalid.")
    expected = {}
    for row in doc["files"]:
        if not isinstance(row, dict) or set(row) != {"path", "size", "sha256"}:
            raise ValueError("Prusa manifest entry is invalid.")
        rel = row["path"]
        if (not isinstance(rel, str) or not rel or rel in expected
                or rel.startswith("/") or "\\" in rel
                or any(part in {"", ".", ".."} for part in rel.split("/"))
                or not isinstance(row["size"], int) or row["size"] < 0
                or not isinstance(row["sha256"], str) or len(row["sha256"]) != 64):
            raise ValueError("Prusa manifest entry is unsafe.")
        expected[rel] = (row["size"], row["sha256"])
    if (len(expected) != doc["file_count"]
            or sum(size for size, _ in expected.values()) != doc["total_bytes"]
            or expected.get("bin/prusa-slicer", (None, None))[1] != BINARY_SHA256
            or expected.get("resources/profiles/PrusaResearch.ini", (None, None))[1] != VENDOR_SHA256
            or "LICENSE" not in expected):
        raise ValueError("Prusa manifest does not match the verified release.")
    actual = {}
    for path in destination.rglob("*"):
        if path.is_symlink() or not (path.is_file() or path.is_dir()):
            raise ValueError("Prusa runtime contains an unsafe file.")
        if path.is_file():
            rel = path.relative_to(destination).as_posix()
            if rel != "review-manifest.json":
                actual[rel] = (path.stat().st_size, sha256(path))
    if actual != expected:
        raise ValueError("Prusa runtime files do not match their SHA-256 manifest.")
    binary = destination / "bin" / "prusa-slicer"
    with binary.open("rb") as source:
        header = source.read(20)
    if (len(header) < 20 or header[:5] != b"\x7fELF\x02"
            or header[5] != 1 or header[18:20] != b"\x3e\x00"):
        raise ValueError("Prusa runtime binary is not Linux AMD64 ELF.")
    binary.chmod(0o555)
    return binary
