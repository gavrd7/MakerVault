import hashlib
import io
import tempfile
from pathlib import Path

from django.contrib.auth import get_user_model
from django.core.files.base import ContentFile
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase, override_settings

from core.models import FileAsset
from core.private_storage import private_storage_key


class StorageVerificationTests(TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.settings_override = override_settings(
            MEDIA_ROOT=Path(self.directory.name), MAKERVAULT_STORAGE_KEY="01" * 32,
            MAKERVAULT_STORAGE_KEY_FILE=None,
        )
        self.settings_override.enable()
        self.addCleanup(self.settings_override.disable)
        self.addCleanup(private_storage_key.cache_clear)
        private_storage_key.cache_clear()
        self.user = get_user_model().objects.create_user(username="restore-owner")
        self.asset = FileAsset.objects.create(
            owner=self.user, name="private.txt", file=ContentFile(b"restore bytes", name="private.txt"),
            sha256=hashlib.sha256(b"restore bytes").hexdigest(),
        )

    def verify(self):
        call_command("verify_private_storage", stdout=io.StringIO(), stderr=io.StringIO())

    def test_success_does_not_change_ciphertext_or_record(self):
        before = Path(self.asset.file.path).read_bytes()
        updated = self.asset.updated_at
        self.verify()
        self.asset.refresh_from_db()
        self.assertEqual(updated, self.asset.updated_at)
        self.assertEqual(before, Path(self.asset.file.path).read_bytes())

    def test_wrong_and_missing_keys_fail(self):
        for key in ["02" * 32, ""]:
            with self.subTest(key_present=bool(key)), override_settings(MAKERVAULT_STORAGE_KEY=key):
                private_storage_key.cache_clear()
                with self.assertRaises(CommandError):
                    self.verify()

    def test_missing_file_fails(self):
        Path(self.asset.file.path).unlink()
        with self.assertRaises(CommandError):
            self.verify()

    def test_damaged_magic_cannot_pass_as_plaintext(self):
        path = Path(self.asset.file.path)
        path.write_bytes(b"BROKEN!!" + path.read_bytes()[8:])
        with self.assertRaises(CommandError):
            self.verify()

    def test_wrong_recorded_checksum_fails(self):
        self.asset.sha256 = "f" * 64
        self.asset.save(update_fields=["sha256"])
        with self.assertRaises(CommandError):
            self.verify()
