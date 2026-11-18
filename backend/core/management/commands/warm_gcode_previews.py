"""Precompute preview caches for existing G-code assets on demand."""
from django.core.management.base import BaseCommand, CommandError

from core.models import FileAsset
from core.tasks import warm_gcode_preview_task


class Command(BaseCommand):
    help = "Queue cached preview generation for the most recent existing G-code files."

    def add_arguments(self, parser):
        parser.add_argument("--recent", type=int, default=5,
                            help="How many recent G-code assets to queue (1–20).")
        parser.add_argument("--now", action="store_true",
                            help="Build caches immediately and report the elapsed time.")
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
            if options["now"]:
                from time import perf_counter
                from core.slicer_preview_cache import warm_asset_overviews
                started = perf_counter()
                with asset.file.storage.open(asset.file.name, "rb") as handle:
                    raw = handle.read(32 * 1024 * 1024 + 1)
                ok = warm_asset_overviews(asset, raw)
                self.stdout.write(
                    f"{asset.name}: {'ready' if ok else 'unsupported'} "
                    f"({perf_counter() - started:.2f}s)"
                )
            else:
                warm_gcode_preview_task.delay(str(asset.pk))
            count += 1
        status = "Prepared" if options["now"] else "Queued"
        self.stdout.write(self.style.SUCCESS(
            f"{status} {count} G-code preview cache task(s). Existing G-code was not changed."
        ))
