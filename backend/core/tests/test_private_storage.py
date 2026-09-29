import os
import tempfile
from pathlib import Path

from django.contrib.auth import get_user_model
from django.core.files.base import ContentFile
from django.core.management import call_command
from django.test import SimpleTestCase, TestCase, override_settings

from core.models import FileAsset
from core.private_storage import (
    HEADER_BYTES,
    MAGIC,
    PrivateEncryptedStorage,
    private_storage_key,
)


TEST_KEY = "00112233445566778899aabbccddeeff00112233445566778899aabbccddeeff"


@override_settings(
    MAKERVAULT_STORAGE_KEY=TEST_KEY,
    MAKERVAULT_STORAGE_KEY_FILE=None,
)
class PrivateEncryptedStorageTests(SimpleTestCase):
    def setUp(self):
        private_storage_key.cache_clear()
        self.tempdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tempdir.cleanup)
        self.storage = PrivateEncryptedStorage(
            location=self.tempdir.name,
            base_url="/media/",
        )

    def tearDown(self):
        private_storage_key.cache_clear()

    def test_new_private_blob_is_opaque_encrypted_and_round_trips(self):
        payload = b"MakerVault private model bytes\x00\x01" * 128
        stored_name = self.storage.save(
            "files/2026/09/revealing-project-name.3mf",
            ContentFile(payload, name="revealing-project-name.3mf"),
        )

        self.assertTrue(stored_name.startswith("private/"))
        self.assertTrue(stored_name.endswith(".blob"))
        self.assertNotIn("revealing-project-name", stored_name)

        with open(self.storage.path(stored_name), "rb") as handle:
            raw = handle.read()
        self.assertTrue(raw.startswith(MAGIC))
        self.assertNotIn(payload[:30], raw)
        self.assertNotEqual(raw, payload)

        self.assertEqual(self.storage.size(stored_name), len(payload))
        with self.storage.open(stored_name, "rb") as handle:
            self.assertEqual(handle.read(), payload)

    def test_ciphertext_tampering_fails_authentication(self):
        payload = b"authenticated maker data" * 64
        stored_name = self.storage.save(
            "secret.stl",
            ContentFile(payload, name="secret.stl"),
        )
        path = self.storage.path(stored_name)

        with open(path, "r+b") as handle:
            handle.seek(HEADER_BYTES + 5)
            original = handle.read(1)
            handle.seek(HEADER_BYTES + 5)
            handle.write(bytes([original[0] ^ 0x01]))

        with self.assertRaises(OSError):
            self.storage.open(stored_name, "rb")

    def test_legacy_plaintext_private_file_remains_readable_during_upgrade(self):
        legacy_name = "files/2026/09/legacy.stl"
        legacy_path = self.storage.path(legacy_name)
        os.makedirs(os.path.dirname(legacy_path), exist_ok=True)
        payload = b"legacy plaintext awaiting migration"
        with open(legacy_path, "wb") as handle:
            handle.write(payload)

        self.assertFalse(self.storage.is_encrypted(legacy_name))
        self.assertEqual(self.storage.size(legacy_name), len(payload))
        with self.storage.open(legacy_name, "rb") as handle:
            self.assertEqual(handle.read(), payload)


class PrivateStorageApplicationIntegrationTests(TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tempdir.cleanup)
        self.override = override_settings(
            MEDIA_ROOT=Path(self.tempdir.name),
            MAKERVAULT_STORAGE_KEY=TEST_KEY,
            MAKERVAULT_STORAGE_KEY_FILE=None,
        )
        self.override.enable()
        self.addCleanup(self.override.disable)
        private_storage_key.cache_clear()

        User = get_user_model()
        self.user = User.objects.create_user(
            username="encrypted-owner",
            email="encrypted-owner@example.com",
            password="test-password",
        )
        self.other = User.objects.create_user(
            username="encrypted-other",
            email="encrypted-other@example.com",
            password="test-password",
        )

    def tearDown(self):
        private_storage_key.cache_clear()

    def test_fileasset_write_and_authenticated_media_delivery_use_encrypted_storage(self):
        payload = b"private CAD/model content"
        asset = FileAsset.objects.create(
            owner=self.user,
            name="private-model.3mf",
            category="slicer",
            file=ContentFile(payload, name="private-model.3mf"),
            metadata={"original_name": "private-model.3mf", "size_bytes": len(payload)},
        )

        self.assertTrue(asset.file.name.startswith("private/"))
        raw_path = Path(asset.file.path)
        self.assertTrue(raw_path.exists())
        self.assertNotEqual(raw_path.read_bytes(), payload)

        self.client.force_login(self.user)
        response = self.client.get(asset.file.url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(b"".join(response.streaming_content), payload)

        self.client.force_login(self.other)
        denied = self.client.get(asset.file.url)
        self.assertEqual(denied.status_code, 404)

    def test_management_command_migrates_legacy_plaintext_and_updates_database_name(self):
        legacy_name = "files/2026/09/legacy-project-file.bin"
        legacy_path = Path(self.tempdir.name) / legacy_name
        legacy_path.parent.mkdir(parents=True, exist_ok=True)
        payload = b"old plaintext private content"
        legacy_path.write_bytes(payload)

        asset = FileAsset.objects.create(
            owner=self.user,
            name="legacy-project-file.bin",
            category="other",
            file=legacy_name,
            metadata={"original_name": "legacy-project-file.bin", "size_bytes": len(payload)},
        )

        call_command("migrate_private_storage", verbosity=0)
        asset.refresh_from_db()

        self.assertTrue(asset.file.name.startswith("private/"))
        self.assertFalse(legacy_path.exists())
        self.assertTrue(asset.file.storage.is_encrypted(asset.file.name))
        with asset.file.storage.open(asset.file.name, "rb") as handle:
            self.assertEqual(handle.read(), payload)
