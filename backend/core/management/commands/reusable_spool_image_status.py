"""Report source-image enrichment outcomes without fetching or modifying data."""
from django.core.management.base import BaseCommand
from core.models import ReusableSpoolCatalogEntry


class Command(BaseCommand):
    help = "Show cached/missing reusable spool images and the latest discovery status."

    def add_arguments(self, parser):
        parser.add_argument("--missing-only", action="store_true")

    def handle(self, *args, **options):
        qs = ReusableSpoolCatalogEntry.objects.order_by("manufacturer", "name")
        count = 0
        for entry in qs:
            if options["missing_only"] and entry.image:
                continue
            meta = entry.provenance or {}
            status = "cached" if entry.image else meta.get("last_image_status") or "not-attempted"
            checked = meta.get("last_image_attempt_at") or "never"
            self.stdout.write(
                f"{entry.key}: {status}; last_attempt={checked}; "
                f"source={entry.source_url or 'none'}"
            )
            count += 1
        self.stdout.write(f"Entries listed: {count}")
