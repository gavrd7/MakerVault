"""Conservatively re-check known reusable spool manufacturer references.

Does not infer or overwrite hardware measurements from arbitrary page text.
"""
from django.core.management.base import BaseCommand
from django.utils import timezone

from core.importers import ImporterError, fetch_catalogue_source_html
from core.models import ReusableSpoolCatalogEntry


class Command(BaseCommand):
    help = "Recheck allow-listed reusable spool source links without changing verified specifications."

    def add_arguments(self, parser):
        parser.add_argument("--limit", type=int, default=20)
        parser.add_argument("--key", default="", help="Check only one catalogue entry key")

    def handle(self, *args, **options):
        rows = ReusableSpoolCatalogEntry.objects.exclude(source_url="")
        if options["key"]:
            rows = rows.filter(key=options["key"])
            if not rows.exists():
                self.stderr.write("No matching catalogue record with a source URL.")
                return
        attempted = successful = 0
        for item in rows.order_by("updated_at", "key")[:max(0, min(options["limit"], 100))]:
            attempted += 1
            status = "ok"
            try:
                _html, final_url = fetch_catalogue_source_html(item.source_url)
            except (ImporterError, ValueError) as exc:
                status = "fetch_failed"
                final_url = item.source_url
                self.stderr.write(f"{item.key}: {exc}")
            metadata = dict(item.provenance or {})
            metadata.update({
                "last_checked_at": timezone.now().isoformat(),
                "last_check_status": status,
                "last_checked_url": final_url,
            })
            item.provenance = metadata
            item.save(update_fields=["provenance", "updated_at"])
            if status == "ok":
                successful += 1
        self.stdout.write(f"Checked {attempted} reusable spool manufacturer sources; {successful} reachable.")
