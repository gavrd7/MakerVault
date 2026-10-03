import hashlib
import importlib.util
import io
from pathlib import Path
import tarfile
import tempfile
import unittest


spec = importlib.util.spec_from_file_location(
    "restore_helper",
    Path(__file__).with_name("restore.py"),
)
restore = importlib.util.module_from_spec(spec)
spec.loader.exec_module(restore)


def make_bundle(path: Path, *, env=b"PUID=1000\nPGID=1000\n", corrupt=False):
    files = {
        "database.dump": b"synthetic database",
        "media.tar.gz": b"synthetic media",
        "keys.tar.gz": b"synthetic keys",
        ".env": env,
        "compose.yaml": b"services: {}\n",
        "recovery-info.json": b'{"format_version": 2}\n',
    }
    lines = []
    for name, payload in files.items():
        value = hashlib.sha256(payload).hexdigest()
        if corrupt and name == "database.dump":
            value = "0" * 64
        lines.append(f"{value}  {name}\n")
    files["SHA256SUMS"] = "".join(lines).encode("utf-8")

    with tarfile.open(path, "w:gz") as archive:
        for name, payload in files.items():
            info = tarfile.TarInfo(f"makervault-backup/{name}")
            info.size = len(payload)
            archive.addfile(info, io.BytesIO(payload))


class RestoreBundleTests(unittest.TestCase):
    def test_verified_bundle_returns_saved_environment(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "backup.mvbackup"
            make_bundle(path)
            result = restore.inspect_local_bundle(path)
            self.assertEqual(result, b"PUID=1000\nPGID=1000\n")

    def test_corrupt_checksum_is_rejected_before_restore(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "backup.mvbackup"
            make_bundle(path, corrupt=True)
            with self.assertRaises(restore.RestoreError):
                restore.inspect_local_bundle(path)

    def test_unsafe_archive_path_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "backup.mvbackup"
            with tarfile.open(path, "w:gz") as archive:
                payload = b"unsafe"
                info = tarfile.TarInfo("../escape")
                info.size = len(payload)
                archive.addfile(info, io.BytesIO(payload))
            with self.assertRaises(restore.RestoreError):
                restore.inspect_local_bundle(path)

    def test_env_ids_defaults_and_validates_numeric_values(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / ".env"
            path.write_text("PUID=911\nPGID=912\n", encoding="utf-8")
            self.assertEqual(restore.env_ids(path), (911, 912))
            path.write_text("PUID=nope\nPGID=912\n", encoding="utf-8")
            with self.assertRaises(restore.RestoreError):
                restore.env_ids(path)


    def test_adapt_recovered_env_appends_replacement_host(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / ".env"
            path.write_text(
                "MAKERVAULT_PORT=8765\n"
                "DJANGO_ALLOWED_HOSTS=localhost,127.0.0.1,192.168.1.10\n"
                "DJANGO_CSRF_TRUSTED_ORIGINS=http://localhost:8765,http://192.168.1.10:8765\n",
                encoding="utf-8",
            )
            added = restore.adapt_recovered_env_for_hosts(path, ["192.168.1.127"])
            self.assertEqual(added, ["192.168.1.127"])
            text = path.read_text(encoding="utf-8")
            self.assertIn(
                "DJANGO_ALLOWED_HOSTS=localhost,127.0.0.1,192.168.1.10,192.168.1.127",
                text,
            )
            self.assertIn(
                "DJANGO_CSRF_TRUSTED_ORIGINS=http://localhost:8765,http://192.168.1.10:8765,http://192.168.1.127:8765",
                text,
            )

    def test_adapt_recovered_env_is_idempotent(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / ".env"
            path.write_text(
                "DJANGO_ALLOWED_HOSTS=localhost,192.168.1.127\n"
                "DJANGO_CSRF_TRUSTED_ORIGINS=http://192.168.1.127:8765\n",
                encoding="utf-8",
            )
            restore.adapt_recovered_env_for_hosts(path, ["192.168.1.127", "192.168.1.127"])
            text = path.read_text(encoding="utf-8")
            self.assertEqual(text.count("192.168.1.127"), 2)

    def test_adapt_recovered_env_rejects_invalid_host(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / ".env"
            path.write_text("PUID=1000\n", encoding="utf-8")
            with self.assertRaises(restore.RestoreError):
                restore.adapt_recovered_env_for_hosts(path, ["not-an-ip"])


if __name__ == "__main__":
    unittest.main()
