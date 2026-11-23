"""Regression for installer/worker UID separation with extracted AppImage trees."""
import os
from pathlib import Path
import stat
from tempfile import TemporaryDirectory
import unittest

from slicer_worker.engine_store_permissions import make_runtime_worker_readable


class RuntimePermissionTests(unittest.TestCase):
    def test_every_supported_installer_engine_has_traversable_runtime(self):
        for engine in ("orcaslicer", "crealityprint", "bambustudio"):
            with self.subTest(engine=engine), TemporaryDirectory() as temp:
                root = Path(temp) / "squashfs-root"
                target = root / "usr" / "bin" / engine
                target.parent.mkdir(parents=True)
                root.chmod(0o700)
                (root / "usr").chmod(0o700)
                target.parent.chmod(0o700)
                target.write_bytes(b"sample executable")
                target.chmod(0o700)
                data = root / "resources" / "profiles.json"
                data.parent.mkdir()
                data.parent.chmod(0o700)
                data.write_text("{}")
                data.chmod(0o600)
                (root / "AppRun").symlink_to("usr/bin/" + engine)
                make_runtime_worker_readable(root)
                for directory in (root, root / "usr", target.parent, data.parent):
                    mode = stat.S_IMODE(directory.stat().st_mode)
                    self.assertEqual(mode & 0o055, 0o055)
                    self.assertEqual(mode & 0o022, 0)
                self.assertEqual(stat.S_IMODE(target.stat().st_mode) & 0o055, 0o055)
                self.assertEqual(stat.S_IMODE(data.stat().st_mode) & 0o044, 0o044)
                self.assertEqual(stat.S_IMODE(data.stat().st_mode) & 0o111, 0)
                self.assertTrue((root / "AppRun").is_symlink())
                self.assertEqual((root / "AppRun").resolve(), target)

    def test_rejects_root_symlink(self):
        with TemporaryDirectory() as temp:
            base = Path(temp)
            real = base / "real"
            real.mkdir()
            (base / "linked").symlink_to(real, target_is_directory=True)
            with self.assertRaisesRegex(ValueError, "Invalid extracted"):
                make_runtime_worker_readable(base / "linked")

    def test_does_not_follow_external_symlinks(self):
        with TemporaryDirectory() as temp:
            root = Path(temp) / "runtime"
            root.mkdir()
            external = Path(temp) / "external"
            external.mkdir()
            secret = external / "secret"
            secret.write_text("untouched")
            secret.chmod(0o600)
            (root / "link").symlink_to(external, target_is_directory=True)
            make_runtime_worker_readable(root)
            self.assertEqual(stat.S_IMODE(secret.stat().st_mode), 0o600)


if __name__ == "__main__":
    unittest.main()
