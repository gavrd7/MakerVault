from django.core.management.base import BaseCommand, CommandError

from core.catalogue_enrichment import run_board_catalogue_enrichment
from core.tasks import enrich_board_catalogue_task


class Command(BaseCommand):
    help = "Enrich missing board technical specifications from supported catalogue sources."

    def add_arguments(self, parser):
        parser.add_argument("--enqueue", action="store_true", help="Queue the work on Celery.")
        parser.add_argument("--limit", type=int, default=None)

    def handle(self, *args, **options):
        if options["enqueue"]:
            try:
                task = enrich_board_catalogue_task.delay(limit=options["limit"])
            except Exception as exc:
                raise CommandError(f"Could not queue board enrichment: {exc}") from exc
            self.stdout.write(self.style.SUCCESS(f"Queued board enrichment task {task.id}."))
            return
        result = run_board_catalogue_enrichment(limit=options["limit"])
        self.stdout.write(self.style.SUCCESS(
            "Board enrichment: "
            f"status={result['status']} processed={result['processed']} "
            f"enriched={result['enriched']} failed={result['failed']} skipped={result['skipped']}"
        ))
