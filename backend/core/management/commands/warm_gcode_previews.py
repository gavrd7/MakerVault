"""Precompute preview caches for existing G-code assets on demand."""
from django.core.management.base import BaseCommand, CommandError

from core.models import FileAsset
from core.tasks import warm_gcode_preview_task


class Command(BaseCommand):
    help = "Queue cached preview generation for the most recent existing G-code files."

    def add_arguments(self, parser):
        parser.add_argument("--recent", type=int, default=5,
                            help="How many recent G-code assets to queue (1–20).")
        parser.add_argument("--asset-id", type=str, default=None,
                            help="Queue one specific G-code file ID instead.")

    def handle(self, *args, **options):
        recent = options["recent"]
        if not 1 <= recent <= 20:
            raise CommandError("--recent must be between 1 and 20.")
        qs = FileAsset.objects.filter(metadata__extension=".gcode").order_by("-created_at")
        if options["asset_id"]:
            try:
                import uuid
                asset_id = uuid.UUID(options["asset_id"])
            except (ValueError, TypeError):
                raise CommandError("--asset-id must be a valid UUID.") from None
            qs = qs.filter(pk=asset_id)
        count = 0
        for asset in qs[:1 if options["asset_id"] else recent]:
            warm_gcode_preview_task.delay(str(asset.pk))
            count += 1
        self.stdout.write(self.style.SUCCESS(
            f"Queued {count} G-code preview cache task(s). Existing G-code was not changed."
        ))
