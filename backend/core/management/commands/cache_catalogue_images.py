from django.core.management.base import BaseCommand
from django.db.models import Q

from core.catalogue_images import CatalogueImageError, cache_catalogue_image_from_url
from core.models import BoardModel, ComponentModel


class Command(BaseCommand):
    help = "Cache remote catalogue images into MakerVault's local media storage."

    def add_arguments(self, parser):
        parser.add_argument("--limit", type=int, default=0, help="Maximum records to process (0 = all).")

    def handle(self, *args, **options):
        limit = max(options["limit"], 0)
        candidates = []

        for kind, queryset in [
            ("board", BoardModel.objects.filter(Q(image="") | Q(image__isnull=True))),
            ("component", ComponentModel.objects.filter(Q(image="") | Q(image__isnull=True))),
        ]:
            for obj in queryset.iterator():
                specs = obj.specifications or {}
                url = specs.get("image_source_url") or specs.get("external_image_url")
                if url:
                    candidates.append((kind, obj, url))

        if limit:
            candidates = candidates[:limit]

        cached = 0
        failed = 0
        for kind, obj, url in candidates:
            try:
                cache_catalogue_image_from_url(obj, url)
                cached += 1
                self.stdout.write(f"cached {kind}: {obj}")
            except CatalogueImageError as exc:
                failed += 1
                self.stderr.write(f"failed {kind}: {obj}: {exc}")

        self.stdout.write(self.style.SUCCESS(f"Catalogue image cache complete: {cached} cached, {failed} failed."))
