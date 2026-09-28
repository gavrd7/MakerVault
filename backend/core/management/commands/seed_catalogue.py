from django.core.management.base import BaseCommand
from django.utils.text import slugify

from core.catalogue_seed import BOARD_DEFINITIONS, CATEGORY_TREE, COMPONENT_DEFINITIONS
from core.catalogue_profiles import apply_board_profile, apply_component_profile
from core.models import (
    BoardCompatibility,
    BoardModel,
    CatalogSource,
    ComponentCategory,
    ComponentModel,
    Manufacturer,
)


def merge_missing_fields(instance, definition, fields):
    changed = False
    for field in fields:
        value = definition.get(field)
        current = getattr(instance, field)
        if value in (None, "", [], {}):
            continue
        if current in (None, "", [], {}):
            setattr(instance, field, value)
            changed = True
        elif isinstance(current, bool) and isinstance(value, bool) and value and not current:
            setattr(instance, field, True)
            changed = True
    return changed


class Command(BaseCommand):
    help = "Seed MakerVault's idempotent starter board/component catalogue."

    def handle(self, *args, **options):
        source, _ = CatalogSource.objects.get_or_create(
            name="MakerVault starter catalogue",
            source_type="manual",
            defaults={"raw_metadata": {"managed_by": "seed_catalogue", "catalogue_version": "0.3.6"}},
        )
        metadata = dict(source.raw_metadata or {})
        metadata.update({"managed_by": "seed_catalogue", "catalogue_version": "0.2.1"})
        source.raw_metadata = metadata
        source.save(update_fields=["raw_metadata", "updated_at"])

        board_created = 0
        board_enriched = 0
        compatibility_created = 0
        for raw_definition in BOARD_DEFINITIONS:
            definition = apply_board_profile(raw_definition)
            maker, _ = Manufacturer.objects.get_or_create(name=definition["manufacturer"])
            defaults = {
                key: value
                for key, value in definition.items()
                if key not in {"manufacturer", "name", "compat"}
            }
            defaults["source"] = source
            defaults.setdefault("specifications", {})
            defaults["specifications"] = {
                **defaults["specifications"],
                "starter_catalogue": True,
                "catalogue_version": "0.2.1",
            }
            board, created = BoardModel.objects.get_or_create(
                manufacturer=maker,
                name=definition["name"],
                variant=definition.get("variant", ""),
                defaults=defaults,
            )
            board_created += int(created)
            if not created and (board.source_id == source.id or board.source_id is None):
                changed = merge_missing_fields(
                    board,
                    defaults,
                    [
                        "family", "mcu", "architecture", "flash_mb", "psram_mb", "ram_kb",
                        "gpio_count", "wifi", "bluetooth", "zigbee", "thread", "usb_connector",
                        "dimensions_mm", "description",
                    ],
                )
                specs = {
                    **(defaults.get("specifications") or {}),
                    **(board.specifications or {}),
                }
                if specs != board.specifications:
                    board.specifications = specs
                    changed = True
                if board.source_id is None:
                    board.source = source
                    changed = True
                if changed:
                    board.save()
                    board_enriched += 1

            for platform in definition.get("compat", []):
                _, compat_created = BoardCompatibility.objects.get_or_create(
                    board=board,
                    platform=platform,
                    defaults={"support_level": "full"},
                )
                compatibility_created += int(compat_created)

        categories = {}
        for category_name, parent_name in CATEGORY_TREE.items():
            parent = categories.get(parent_name) if parent_name else None
            category, _ = ComponentCategory.objects.get_or_create(
                slug=slugify(category_name)[:140],
                defaults={"name": category_name, "parent": parent},
            )
            if parent and category.parent_id != parent.id:
                category.parent = parent
                category.save(update_fields=["parent", "updated_at"])
            categories[category_name] = category

        component_created = 0
        component_enriched = 0
        for raw_definition in COMPONENT_DEFINITIONS:
            definition = apply_component_profile(raw_definition)
            category = categories[definition["category"]]
            specs = {
                **definition.get("specifications", {}),
                "starter_catalogue": True,
                "catalogue_version": "0.2.1",
            }
            component = (
                ComponentModel.objects.filter(
                    name=definition["name"],
                    part_number=definition.get("part_number", ""),
                )
                .order_by("created_at", "pk")
                .first()
            )
            created = component is None
            if created:
                component = ComponentModel.objects.create(
                    name=definition["name"],
                    part_number=definition.get("part_number", ""),
                    category=category,
                    source=source,
                    description=definition.get("description", ""),
                    specifications=specs,
                )
            component_created += int(created)
            if not created and (component.source_id == source.id or component.source_id is None):
                changed = False
                if component.category_id is None:
                    component.category = category
                    changed = True
                if component.source_id is None:
                    component.source = source
                    changed = True
                if not component.description and definition.get("description"):
                    component.description = definition["description"]
                    changed = True
                merged_specs = {**specs, **(component.specifications or {})}
                if merged_specs != component.specifications:
                    component.specifications = merged_specs
                    changed = True
                if changed:
                    component.save()
                    component_enriched += 1

        self.stdout.write(
            self.style.SUCCESS(
                "Starter catalogue ready: "
                f"{board_created} boards added, {board_enriched} boards enriched, "
                f"{component_created} components added, {component_enriched} components enriched, "
                f"{compatibility_created} compatibility records added."
            )
        )
