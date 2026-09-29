from django.core.management.base import BaseCommand, CommandError

from core.catalogue_image_sources import run_catalogue_image_seed
from core.tasks import seed_catalogue_images_task


class Command(BaseCommand):
    help = "Populate missing starter catalogue images from approved online sources."

    def add_arguments(self, parser):
        parser.add_argument("--enqueue", action="store_true", help="Queue the work on Celery and return immediately.")
        parser.add_argument("--limit", type=int, default=None, help="Maximum records to attempt in this run.")
        parser.add_argument("--force-retry", action="store_true", help="Retry records attempted recently.")
        parser.add_argument(
            "--kind",
            action="append",
            choices=["printers", "boards", "components"],
            help="Limit the pass to one catalogue kind. Repeat to include more than one.",
        )

    def handle(self, *args, **options):
        if options["enqueue"]:
            try:
                result = seed_catalogue_images_task.delay(
                    limit=options["limit"],
                    force_retry=options["force_retry"],
                    kinds=options.get("kind") or None,
                )
            except Exception as exc:
                raise CommandError(f"Could not queue catalogue image seeding: {exc}") from exc
            self.stdout.write(self.style.SUCCESS(f"Queued catalogue image seeding task {result.id}."))
            return

        result = run_catalogue_image_seed(
            limit=options["limit"],
            force_retry=options["force_retry"],
            kinds=options.get("kind") or None,
        )
        self.stdout.write(
            self.style.SUCCESS(
                "Catalogue image seeding: "
                f"status={result['status']} processed={result['processed']} "
                f"cached={result['cached']} failed={result['failed']} skipped={result['skipped']}"
            )
        )
        for kind, stats in (result.get("by_kind") or {}).items():
            self.stdout.write(
                f"  {kind}: processed={stats['processed']} cached={stats['cached']} "
                f"failed={stats['failed']} skipped={stats['skipped']}"
            )
        if result.get("by_provider"):
            self.stdout.write(
                "  providers: " + ", ".join(
                    f"{provider}={count}"
                    for provider, count in sorted(result["by_provider"].items())
                )
            )
        if result.get("failures"):
            self.stdout.write("  sample failures:")
            for item in result["failures"][:10]:
                self.stdout.write(
                    f"    - {item['kind']} {item['name']} [{item['variant']}]: {item['reason']}"
                )
