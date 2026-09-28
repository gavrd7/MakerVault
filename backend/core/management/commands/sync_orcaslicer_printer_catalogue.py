from django.core.management.base import BaseCommand, CommandError

from core.orcaslicer_catalogue import OrcaCatalogueError, sync_orcaslicer_printer_catalogue


class Command(BaseCommand):
    help = "Synchronise MakerVault's 3D-printer model catalogue from OrcaSlicer."

    def add_arguments(self, parser):
        parser.add_argument("--ref", default=None, help="OrcaSlicer Git ref (default: configured ref/main)")
        parser.add_argument("--workers", type=int, default=8, help="Concurrent vendor manifest fetches")
        parser.add_argument(
            "--best-effort",
            action="store_true",
            help="Report a warning instead of failing when OrcaSlicer is unavailable.",
        )

    def handle(self, *args, **options):
        try:
            result = sync_orcaslicer_printer_catalogue(
                ref=options.get("ref"),
                max_workers=options.get("workers") or 8,
            )
        except OrcaCatalogueError as exc:
            if options.get("best_effort"):
                self.stdout.write(self.style.WARNING(f"OrcaSlicer catalogue sync skipped: {exc}"))
                return
            raise CommandError(str(exc)) from exc

        self.stdout.write(
            self.style.SUCCESS(
                "OrcaSlicer printer catalogue sync: "
                f"{result['models_seen']} models across {result['vendors_seen']} vendors; "
                f"{result['models_created']} added, {result['models_enriched']} enriched, "
                f"{result['manufacturers_created']} manufacturers added"
                + (
                    f", {len(result['failed_vendors'])} vendor manifests unavailable."
                    if result["failed_vendors"]
                    else "."
                )
            )
        )
