"""Cache an explicitly reviewed reusable-spool product image with MakerVault's SSRF-safe image fetcher."""
from django.core.management.base import BaseCommand, CommandError

from core.catalogue_images import CatalogueImageError, cache_catalogue_image_from_url
from core.models import ReusableSpoolCatalogEntry


class Command(BaseCommand):
    help = "Cache a vetted public product image for a known manufacturer reusable spool."

    def add_arguments(self, parser):
        parser.add_argument("key", help="Stable catalogue entry key")
        parser.add_argument("image_url", help="Reviewed, publicly accessible image URL")
        parser.add_argument("--replace", action="store_true", help="Replace an existing cached image")

    def handle(self, *args, **options):
        entry = ReusableSpoolCatalogEntry.objects.filter(key=options["key"]).first()
        if not entry:
            raise CommandError("No reusable spool catalogue entry has that key.")
        if entry.image and not options["replace"]:
            raise CommandError("An image is already cached. Pass --replace to update it.")
        try:
            cache_catalogue_image_from_url(entry, options["image_url"])
        except (CatalogueImageError, ValueError, OSError) as exc:
            raise CommandError(f"Image could not be safely cached: {exc}") from exc
        entry.image_url = options["image_url"]
        entry.save(update_fields=["image_url", "updated_at"])
        self.stdout.write(self.style.SUCCESS(f"Cached manufacturer image for {entry.name}"))
