import os
import tempfile

from django.core.files.base import ContentFile
from django.test import SimpleTestCase, override_settings

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
