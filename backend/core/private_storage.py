from __future__ import annotations

import base64
import binascii
import logging
import os
import struct
import tempfile
import uuid
from functools import lru_cache

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured, SuspiciousFileOperation
from django.core.files import File
from django.core.files.storage import FileSystemStorage
from django.utils.deconstruct import deconstructible


logger = logging.getLogger(__name__)

MAGIC = b"MVLTENC1"
NONCE_BYTES = 12
SIZE_BYTES = 8
TAG_BYTES = 16
HEADER_BYTES = len(MAGIC) + NONCE_BYTES + SIZE_BYTES
CHUNK_BYTES = 1024 * 1024


def _decode_key(raw) -> bytes:
    if isinstance(raw, bytes):
        stripped_bytes = raw.strip()
        if len(raw) == 32 and any(byte < 32 or byte > 126 for byte in raw):
            return raw
        try:
            text = stripped_bytes.decode("ascii")
        except UnicodeDecodeError:
            if len(raw) == 32:
                return raw
            raise ImproperlyConfigured("MakerVault private-storage key must be 32 bytes or encoded text.")
    else:
        text = str(raw or "").strip()

    if not text:
        raise ImproperlyConfigured("MakerVault private-storage encryption key is not configured.")

    if len(text) == 64:
        try:
            decoded = bytes.fromhex(text)
            if len(decoded) == 32:
                return decoded
        except ValueError:
            pass

    try:
        padded = text + ("=" * (-len(text) % 4))
        decoded = base64.urlsafe_b64decode(padded.encode("ascii"))
        if len(decoded) == 32:
            return decoded
    except (ValueError, UnicodeEncodeError, binascii.Error):
        pass

    raise ImproperlyConfigured(
        "MAKERVAULT_STORAGE_KEY must decode to exactly 32 bytes (AES-256)."
    )


@lru_cache(maxsize=1)
def private_storage_key() -> bytes:
    inline = str(getattr(settings, "MAKERVAULT_STORAGE_KEY", "") or "").strip()
    if inline:
        return _decode_key(inline)

    key_file = getattr(settings, "MAKERVAULT_STORAGE_KEY_FILE", None)
    if key_file:
        path = os.fspath(key_file)
        try:
            with open(path, "rb") as handle:
                return _decode_key(handle.read())
        except FileNotFoundError as exc:
            raise ImproperlyConfigured(
                "MakerVault private-storage key file does not exist. "
                "Restore the key volume/file before accessing encrypted data."
            ) from exc

    raise ImproperlyConfigured(
        "Configure MAKERVAULT_STORAGE_KEY or MAKERVAULT_STORAGE_KEY_FILE "
        "before writing private MakerVault files."
    )


def private_storage_key_status() -> dict:
    try:
        private_storage_key()
        return {"configured": True}
    except ImproperlyConfigured:
        return {"configured": False}


def _content_size(content) -> int:
    try:
        value = getattr(content, "size", None)
        if value is not None:
            return max(int(value), 0)
    except (TypeError, ValueError, OSError):
        pass

    try:
        position = content.tell()
        content.seek(0, os.SEEK_END)
        value = content.tell()
        content.seek(position)
        return max(int(value), 0)
    except (AttributeError, OSError, TypeError, ValueError) as exc:
        raise SuspiciousFileOperation("Unable to determine uploaded file size for encryption.") from exc


@deconstructible
class PrivateEncryptedStorage(FileSystemStorage):
    """AES-256-GCM storage for user-private MakerVault blobs.

    New writes receive opaque object names. Existing pre-v0.7 plaintext objects
    remain readable so installations can migrate them safely with the dedicated
    management command.
    """

    def _opaque_name(self) -> str:
        token = uuid.uuid4().hex
        return f"private/{token[:2]}/{token}.blob"

    def _save(self, name, content):
        key = private_storage_key()
        plaintext_size = _content_size(content)

        object_name = self._opaque_name()
        while self.exists(object_name):
            object_name = self._opaque_name()
        path = self.path(object_name)
        os.makedirs(os.path.dirname(path), exist_ok=True)

        nonce = os.urandom(NONCE_BYTES)
        header = MAGIC + nonce + struct.pack(">Q", plaintext_size)
        encryptor = Cipher(algorithms.AES(key), modes.GCM(nonce)).encryptor()
        encryptor.authenticate_additional_data(header)

        written = 0
        try:
            with open(path, "xb") as destination:
                destination.write(header)
                if hasattr(content, "chunks"):
                    chunks = content.chunks(CHUNK_BYTES)
                else:
                    def reader():
                        while True:
                            chunk = content.read(CHUNK_BYTES)
                            if not chunk:
                                break
                            yield chunk
                    chunks = reader()

                for chunk in chunks:
                    if not chunk:
                        continue
                    written += len(chunk)
                    destination.write(encryptor.update(chunk))
                destination.write(encryptor.finalize())
                destination.write(encryptor.tag)

            if written != plaintext_size:
                raise SuspiciousFileOperation(
                    f"Private file size changed during encryption ({plaintext_size} expected, {written} read)."
                )

            if self.file_permissions_mode is not None:
                os.chmod(path, self.file_permissions_mode)
            return object_name
        except Exception:
            try:
                os.remove(path)
            except FileNotFoundError:
                pass
            raise

    def _open(self, name, mode="rb"):
        if mode not in {"r", "rb"}:
            raise ValueError("Encrypted private storage is read-only through open(); use storage.save() for writes.")

        raw = open(self.path(name), "rb")
        prefix = raw.read(len(MAGIC))
        if prefix != MAGIC:
            raw.seek(0)
            return File(raw, name=name)

        rest = raw.read(NONCE_BYTES + SIZE_BYTES)
        if len(rest) != NONCE_BYTES + SIZE_BYTES:
            raw.close()
            raise OSError("Encrypted MakerVault object has a truncated header.")

        nonce = rest[:NONCE_BYTES]
        plaintext_size = struct.unpack(">Q", rest[NONCE_BYTES:])[0]
        header = MAGIC + rest

        raw.seek(0, os.SEEK_END)
        total_size = raw.tell()
        expected_total = HEADER_BYTES + plaintext_size + TAG_BYTES
        if total_size != expected_total:
            raw.close()
            raise OSError("Encrypted MakerVault object length does not match its authenticated header.")

        raw.seek(total_size - TAG_BYTES)
        tag = raw.read(TAG_BYTES)
        raw.seek(HEADER_BYTES)

        decryptor = Cipher(algorithms.AES(private_storage_key()), modes.GCM(nonce, tag)).decryptor()
        decryptor.authenticate_additional_data(header)
        temporary = tempfile.SpooledTemporaryFile(
            max_size=max(int(getattr(settings, "FILE_UPLOAD_MAX_MEMORY_SIZE", 10 * 1024 * 1024)), 1024 * 1024),
            mode="w+b",
        )

        remaining = plaintext_size
        try:
            while remaining:
                chunk = raw.read(min(CHUNK_BYTES, remaining))
                if not chunk:
                    raise OSError("Encrypted MakerVault object ended unexpectedly.")
                remaining -= len(chunk)
                temporary.write(decryptor.update(chunk))
            temporary.write(decryptor.finalize())
            temporary.seek(0)
            return File(temporary, name=name)
        except InvalidTag as exc:
            temporary.close()
            logger.error("Authentication failed while decrypting private MakerVault object %s", name)
            raise OSError("Encrypted MakerVault object failed authentication.") from exc
        except Exception:
            temporary.close()
            raise
        finally:
            raw.close()

    def size(self, name):
        try:
            path = self.path(name)
            with open(path, "rb") as handle:
                prefix = handle.read(len(MAGIC))
                if prefix != MAGIC:
                    return super().size(name)
                rest = handle.read(NONCE_BYTES + SIZE_BYTES)
                if len(rest) != NONCE_BYTES + SIZE_BYTES:
                    raise OSError("Encrypted MakerVault object has a truncated header.")
                plaintext_size = int(struct.unpack(">Q", rest[NONCE_BYTES:])[0])
            expected_total = HEADER_BYTES + plaintext_size + TAG_BYTES
            if os.path.getsize(path) != expected_total:
                raise OSError("Encrypted MakerVault object length does not match its authenticated header.")
            return plaintext_size
        except FileNotFoundError:
            raise

    def is_encrypted(self, name) -> bool:
        try:
            with open(self.path(name), "rb") as handle:
                return handle.read(len(MAGIC)) == MAGIC
        except FileNotFoundError:
            return False


private_storage = PrivateEncryptedStorage()
