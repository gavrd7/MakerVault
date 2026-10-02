import hashlib

from django.apps import apps
from django.core.management.base import BaseCommand, CommandError
from django.db.models import FileField

from core.private_storage import MAGIC, PrivateEncryptedStorage, private_storage_key


class Command(BaseCommand):
    help = "Read and authenticate every referenced private file without changing records or storage."

    def handle(self, *args, **options):
        # Validate even an empty installation: do not report a missing key as success.
        try:
            private_storage_key()
        except Exception as exc:
            raise CommandError("Private-storage key is missing or invalid; restore the original key.") from exc
        checked = failed = legacy = 0
        for model in apps.get_app_config("core").get_models():
            for field in model._meta.fields:
                if not isinstance(field, FileField) or not isinstance(field.storage, PrivateEncryptedStorage):
                    continue
                rows = model.objects.exclude(**{field.name: ""}).exclude(**{field.name: None})
                for obj in rows.iterator():
                    stored = getattr(obj, field.name)
                    checked += 1
                    try:
                        with open(stored.path, "rb") as raw:
                            encrypted = raw.read(len(MAGIC)) == MAGIC
                        # Legacy files are readable, but damaged opaque blobs must
                        # never silently pass as legacy plaintext.
                        if not encrypted and stored.name.startswith("private/"):
                            raise OSError("Invalid encrypted-object header")
                        digest = hashlib.sha256()
                        with stored.open("rb") as handle:
                            for chunk in handle.chunks():
                                digest.update(chunk)
                        expected = getattr(obj, "sha256", "")
                        if expected and digest.hexdigest() != expected:
                            raise OSError("Content checksum mismatch")
                        if not encrypted:
                            legacy += 1
                    except Exception:
                        failed += 1
                        # Do not print filenames, keys, exception text or contents.
                        self.stderr.write(f"FAILED {model._meta.label}.{field.name} record={obj.pk}")
        self.stdout.write(f"Private storage: checked={checked}, legacy={legacy}, failed={failed}")
        if failed:
            raise CommandError("Private-file verification failed. Preserve the backup and investigate before use.")
        if legacy:
            self.stdout.write(self.style.WARNING("Legacy plaintext files remain; review the private-storage migration."))
        self.stdout.write(self.style.SUCCESS("All referenced private files are readable and checksums match where recorded."))
