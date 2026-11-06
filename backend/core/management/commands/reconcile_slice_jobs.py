"""Administrative recovery for abandoned slicing jobs; never retries slicing."""
from django.core.management.base import BaseCommand, CommandError

from core.slicer_execution import SlicerExecutionError, reconcile_stale_jobs


class Command(BaseCommand):
    help = "Mark overdue slicing jobs stale without requeueing or starting printers."

    def add_arguments(self, parser):
        parser.add_argument("--limit", type=int, default=250)

    def handle(self, *args, **options):
        try:
            counts = reconcile_stale_jobs(limit=options["limit"])
        except SlicerExecutionError as exc:
            raise CommandError(str(exc)) from exc
        self.stdout.write(
            self.style.SUCCESS(
                "Slicer reconciliation: "
                f"{counts['queued']} queued and {counts['running']} running jobs marked stale."
            )
        )
