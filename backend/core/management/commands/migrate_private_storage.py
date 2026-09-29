from django.core.files import File
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from core.models import FileAsset, InventoryItem, Project
from core.private_storage import private_storage, private_storage_key


class Command(BaseCommand):
    help = (
        "Encrypt legacy plaintext user-private media into opaque MakerVault blobs. "
        "New uploads are encrypted automatically; this command upgrades existing files."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Report legacy private files without changing storage.",
        )

    def _iter_fields(self):
        for obj in FileAsset.objects.exclude(file="").iterator():
            yield obj, "file"
        for obj in Project.objects.exclude(cover_image="").iterator():
            yield obj, "cover_image"
        for obj in InventoryItem.objects.exclude(image="").iterator():
            yield obj, "image"

    def handle(self, *args, **options):
        try:
            private_storage_key()
        except Exception as exc:
            raise CommandError(str(exc)) from exc

        dry_run = bool(options["dry_run"])
        scanned = migrated = missing = already = failed = 0

        for obj, field_name in self._iter_fields():
            scanned += 1
            field = getattr(obj, field_name)
            old_name = str(field.name or "")
            if not old_name:
                continue
            if private_storage.is_encrypted(old_name):
                already += 1
                continue
            if not private_storage.exists(old_name):
                missing += 1
                self.stderr.write(
                    self.style.WARNING(f"Missing private media object: {old_name}")
                )
                continue
            if dry_run:
                migrated += 1
                continue

            new_name = None
            try:
                with private_storage.open(old_name, "rb") as source:
                    new_name = private_storage.save(old_name, File(source, name=old_name))

                with transaction.atomic():
                    locked = obj.__class__.objects.select_for_update().get(pk=obj.pk)
                    current = getattr(locked, field_name)
                    if str(current.name or "") != old_name:
                        private_storage.delete(new_name)
                        self.stderr.write(
                            self.style.WARNING(
                                f"Skipped changed record {obj.__class__.__name__} {obj.pk}"
                            )
                        )
                        continue
                    current.name = new_name
                    setattr(locked, field_name, current)
                    update_fields = [field_name]
                    if hasattr(locked, "updated_at"):
                        update_fields.append("updated_at")
                    locked.save(update_fields=update_fields)

                private_storage.delete(old_name)
                migrated += 1
            except Exception as exc:
                failed += 1
                if new_name:
                    try:
                        private_storage.delete(new_name)
                    except Exception:
                        pass
                self.stderr.write(
                    self.style.ERROR(
                        f"Failed {obj.__class__.__name__} {obj.pk}: {exc}"
                    )
                )

        verb = "would migrate" if dry_run else "migrated"
        self.stdout.write(
            self.style.SUCCESS(
                f"Private storage scan complete: {scanned} scanned, {migrated} {verb}, "
                f"{already} already encrypted, {missing} missing, {failed} failed."
            )
        )
        if failed:
            raise CommandError(
                "One or more private files failed migration; no failed source object was deleted."
            )
