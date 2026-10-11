"""Inspect possible spool images without downloading or modifying image records.

Candidates are for human review only, not automatically approved product photos.
"""
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup
from django.core.management.base import BaseCommand, CommandError

from core.importers import ImporterError, fetch_catalogue_source_html
from core.models import ReusableSpoolCatalogEntry
from core.reusable_spool_images import official_image_candidate


class Command(BaseCommand):
    help = "Inspect source-page image candidates for one spool; never cache automatically."

    def add_arguments(self, parser):
        parser.add_argument("key", help="Exact reusable spool catalogue key")
        parser.add_argument("--limit", type=int, default=12)

    def handle(self, *args, **options):
        entry = ReusableSpoolCatalogEntry.objects.filter(key=options["key"]).first()
        if entry is None:
            raise CommandError("Unknown spool catalogue key.")
        if not entry.source_url:
            raise CommandError("No source URL for this catalogue entry.")
        try:
            final_url, html = fetch_catalogue_source_html(entry.source_url)
        except (ImporterError, ValueError, OSError) as exc:
            raise CommandError(f"Unable to inspect product page: {exc}") from exc

        soup = BeautifulSoup(html, "html.parser")
        self.stdout.write(f"Entry: {entry.manufacturer} — {entry.name}")
        self.stdout.write(f"Page: {final_url}")
        self.stdout.write(f"Auto-approved metadata match: {official_image_candidate(entry, html, final_url) or 'none'}")
        self.stdout.write("Other image URLs (review manually; may depict refill packs or unrelated items):")
        candidates = []
        seen = set()
        tags = [
            *soup.select('meta[property="og:image"], meta[name="twitter:image"], meta[property="twitter:image"]'),
            *soup.select("img[src], img[data-src]"),
        ]
        for tag in tags:
            raw = (tag.get("content") if tag.name == "meta"
                   else tag.get("data-src") or tag.get("src")) or ""
            raw = raw.strip()
            if not raw or raw.startswith(("data:", "blob:")):
                continue
            absolute = urljoin(final_url, raw)
            parsed = urlparse(absolute)
            if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
                continue
            if absolute in seen:
                continue
            seen.add(absolute)
            candidates.append((absolute, str(tag.get("alt") or "")[:100]))
            if len(candidates) >= max(0, min(options["limit"], 30)):
                break
        for i, (url, alt) in enumerate(candidates, 1):
            self.stdout.write(f"  {i}. {url}" + (f" [alt: {alt}]" if alt else ""))
        self.stdout.write(f"Candidates listed: {len(candidates)} (none cached)")
