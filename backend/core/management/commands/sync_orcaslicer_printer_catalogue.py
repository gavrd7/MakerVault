from django.core.management.base import BaseCommand, CommandError

from core.models import PrinterCatalogModel
from core.orcaslicer_catalogue import OrcaCatalogueError, sync_orcaslicer_printer_catalogue


class Command(BaseCommand):
    help = "Synchronise MakerVault's 3D-printer model catalogue from OrcaSlicer."

    def add_arguments(self, parser):
        parser.add_argument("--ref", default=None, help="OrcaSlicer Git ref (default: configured ref/main)")
        parser.add_argument("--workers", type=int, default=8, help="Concurrent vendor manifest fetches")
        parser.add_argument(
            "--if-sparse",
            type=int,
            default=0,
            help="Only sync when the local printer catalogue has fewer than this many models.",
        )
        parser.add_argument(
            "--best-effort",
            action="store_true",
            help="Report a warning instead of failing when OrcaSlicer is unavailable.",
        )

    def handle(self, *args, **options):
        sparse_threshold = max(int(options.get("if_sparse") or 0), 0)
        if sparse_threshold and PrinterCatalogModel.objects.count() >= sparse_threshold:
            self.stdout.write(
                f"OrcaSlicer catalogue startup sync skipped: local catalogue already has "
                f"{PrinterCatalogModel.objects.count()} models."
            )
            return

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
                f"{result.get('hardware_profiles_enriched', 0)} hardware profiles resolved, "
                f"{result['manufacturers_created']} manufacturers added"
                + (
                    f", {len(result['failed_vendors'])} vendor manifests unavailable."
                    if result["failed_vendors"]
                    else "."
                )
            )
        )
        if result.get("failed_vendors"):
            self.stdout.write(self.style.WARNING("Unavailable Orca vendor manifests:"))
            for item in result["failed_vendors"]:
                self.stdout.write(
                    f"  - {item.get('file') or 'unknown'}: {item.get('error') or 'unknown error'}"
                )
