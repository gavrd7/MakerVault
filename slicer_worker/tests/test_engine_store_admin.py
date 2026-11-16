"""Host-only engine-store copy/activation/rollback tests without Docker."""
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from slicer_worker import engine_store_admin as admin


class EngineStoreAdminTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.base = Path(tmp.name)
        self.source = self.base / "bundle"
        self.source.mkdir()
        self.store = self.base / "engine-volume"
        self.store.mkdir()
        self.binary = self.source / "orcaslicer.AppImage"
        self.binary.write_bytes(b"reviewed test executable")
        self.binary.chmod(0o755)
        self.sha = hashlib.sha256(self.binary.read_bytes()).hexdigest()
        appdir = self.source / "squashfs-root"
        appdir.mkdir()
        (appdir / "AppRun").write_bytes(b"runtime")
        (appdir / "AppRun").chmod(0o755)
        p = patch.object(admin, "EXPECTED_ORCA_SHA", self.sha)
        p.start()
        self.addCleanup(p.stop)

    def test_seed_preserves_bytes_and_activation(self):
        path = admin.seed_bundled_orca(self.store, self.source)
        self.assertEqual(path, self.store / "versions/orcaslicer/2.5.0")
        self.assertEqual(hashlib.sha256((path / "orcaslicer.AppImage").read_bytes()).hexdigest(), self.sha)
        record = admin.activate(self.store, engine="orcaslicer", version="2.5.0", sha256=self.sha)
        self.assertEqual(record["engines"]["orcaslicer"]["version"], "2.5.0")
        self.assertEqual(admin._manifest(self.store), record)

    def test_seed_cannot_overwrite_existing_engine(self):
        admin.seed_bundled_orca(self.store, self.source)
        with self.assertRaisesRegex(ValueError, "already exists"):
            admin.seed_bundled_orca(self.store, self.source)

    def test_checksum_mismatch_refuses_seed(self):
        with patch.object(admin, "EXPECTED_ORCA_SHA", "0" * 64):
            with self.assertRaisesRegex(ValueError, "digest"):
                admin.seed_bundled_orca(self.store, self.source)

    def test_bad_activation_is_rejected(self):
        admin.seed_bundled_orca(self.store, self.source)
        for version, checksum in [("../2.5.0", self.sha), ("2.5.0", "0" * 64)]:
            with self.subTest(version=version, checksum=checksum):
                with self.assertRaises(ValueError):
                    admin.activate(self.store, engine="orcaslicer", version=version, sha256=checksum)

    def test_rollback_previous_selection(self):
        admin.seed_bundled_orca(self.store, self.source)
        admin.activate(self.store, engine="orcaslicer", version="2.5.0", sha256=self.sha)
        # A second approved installation with an explicit distinct version.
        v2 = self.store / "versions/orcaslicer/2.5.0-next"
        v2.mkdir()
        (v2 / "orcaslicer.AppImage").write_bytes(b"separately approved candidate")
        (v2 / "orcaslicer.AppImage").chmod(0o755)
        (v2 / "squashfs-root").mkdir()
        (v2 / "squashfs-root/AppRun").write_bytes(b"runtime")
        digest = hashlib.sha256((v2 / "orcaslicer.AppImage").read_bytes()).hexdigest()
        admin.activate(self.store, engine="orcaslicer", version="2.5.0-next", sha256=digest)
        result = admin.rollback(self.store)
        self.assertEqual(result["engines"]["orcaslicer"]["version"], "2.5.0")
        self.assertTrue(v2.is_dir())


if __name__ == "__main__":
    unittest.main()
