"""Offline regression suite for exact-source Prusa tar admission and lifecycle.

No upstream downloads, runtime execution, server or existing engine is touched.
"""
import hashlib
import io
import json
from pathlib import Path
import struct
import tarfile
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from slicer_worker import prusa_runtime_install as prusa


def fixture_archive(path, *, bad_extra=False, symlink=False, bad_manifest=False,
                    wrong_arch=False):
    binary = (b"\x7fELF\x02\x01" + b"\x00" * 12
              + (b"\xb7\x00" if wrong_arch else b"\x3e\x00")
              + b"safe-test-binary")
    payload = {
        "bin/prusa-slicer": binary,
        "resources/profiles/PrusaResearch.ini": b"[printer:fixture]\n",
        "LICENSE": b"licence test fixture",
    }
    if bad_extra:
        payload["unexpected-extra"] = b"should be rejected"
    rows = [{"path": name, "size": len(data),
             "sha256": hashlib.sha256(data).hexdigest()}
            for name, data in payload.items() if name != "unexpected-extra"]
    doc = {"schema": 1, "engine": "prusaslicer", "version": "2.9.7",
           "platform": "linux/amd64", "source_tag": prusa.SOURCE_TAG,
           "source_commit": prusa.SOURCE_COMMIT, "install_approved": False,
           "file_count": len(rows), "total_bytes": sum(x["size"] for x in rows),
           "files": rows}
    if bad_manifest:
        doc["source_commit"] = "0" * 40
    payload["review-manifest.json"] = json.dumps(doc).encode()
    with tarfile.open(path, "w:gz") as tar:
        root = tarfile.TarInfo("prusa-candidate")
        root.type = tarfile.DIRTYPE
        tar.addfile(root)
        for name, data in payload.items():
            item = tarfile.TarInfo("prusa-candidate/" + name)
            item.size = len(data)
            tar.addfile(item, io.BytesIO(data))
        if symlink:
            link = tarfile.TarInfo("prusa-candidate/evil-link")
            link.type = tarfile.SYMTYPE
            link.linkname = "../../etc/passwd"
            tar.addfile(link)
    return payload


class PrusaBundleTests(unittest.TestCase):
    def check(self, archive, destination, payload):
        with patch.object(prusa, "ASSET_SIZE", archive.stat().st_size), \
             patch.object(prusa, "ARCHIVE_SHA256", prusa.sha256(archive)), \
             patch.object(prusa, "BINARY_SHA256", hashlib.sha256(payload["bin/prusa-slicer"]).hexdigest()), \
             patch.object(prusa, "VENDOR_SHA256", hashlib.sha256(payload["resources/profiles/PrusaResearch.ini"]).hexdigest()):
            return prusa.unpack_reviewed_prusa(archive, destination)

    def test_real_archive_shape_and_exact_identity(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            archive = root / "source.tar.gz"
            payload = fixture_archive(archive)
            destination = root / "install"
            destination.mkdir()
            binary = self.check(archive, destination, payload)
            self.assertEqual(binary.read_bytes(), payload["bin/prusa-slicer"])
            self.assertEqual(binary.stat().st_mode & 0o111, 0o111)
            self.assertTrue((destination / "LICENSE").is_file())

    def test_unknown_extra_file_is_rejected(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            archive = root / "source.tar.gz"
            payload = fixture_archive(archive, bad_extra=True)
            (root / "stage").mkdir()
            with self.assertRaisesRegex(ValueError, "SHA-256 manifest"):
                self.check(archive, root / "stage", payload)

    def test_symlink_is_never_extracted(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            archive = root / "source.tar.gz"
            payload = fixture_archive(archive, symlink=True)
            (root / "stage").mkdir()
            with self.assertRaisesRegex(ValueError, "unsafe"):
                self.check(archive, root / "stage", payload)

    def test_wrong_source_commit_fails_closed(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            archive = root / "source.tar.gz"
            payload = fixture_archive(archive, bad_manifest=True)
            (root / "stage").mkdir()
            with self.assertRaisesRegex(ValueError, "identity"):
                self.check(archive, root / "stage", payload)

    def test_wrong_elf_machine_is_rejected(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            archive = root / "source.tar.gz"
            payload = fixture_archive(archive, wrong_arch=True)
            (root / "stage").mkdir()
            with self.assertRaisesRegex(ValueError, "AMD64 ELF"):
                self.check(archive, root / "stage", payload)

    def test_wrong_archive_digest_is_rejected_before_extraction(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            archive = root / "source.tar.gz"
            fixture_archive(archive)
            (root / "stage").mkdir()
            with patch.object(prusa, "ASSET_SIZE", archive.stat().st_size), \
                 patch.object(prusa, "ARCHIVE_SHA256", "0" * 64):
                with self.assertRaisesRegex(ValueError, "exact release"):
                    prusa.unpack_reviewed_prusa(archive, root / "stage")
            self.assertEqual(list((root / "stage").iterdir()), [])


if __name__ == "__main__":
    unittest.main()
