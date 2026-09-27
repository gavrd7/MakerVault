from django.core.management.base import BaseCommand

from core.models import PrinterCatalogModel, PrinterManufacturer
from core.printing_catalogue_seed import PRINTER_CATALOGUE


class Command(BaseCommand):
    help = "Seed MakerVault's idempotent starter 3D-printer catalogue."

    def handle(self, *args, **options):
        makers_created = 0
        models_created = 0
        models_enriched = 0

        for manufacturer_data in PRINTER_CATALOGUE:
            maker, created = PrinterManufacturer.objects.get_or_create(
                name=manufacturer_data["manufacturer"],
                defaults={"website": manufacturer_data.get("website", "")},
            )
            makers_created += int(created)
            if not maker.website and manufacturer_data.get("website"):
                maker.website = manufacturer_data["website"]
                maker.save(update_fields=["website", "updated_at"])

            for definition in manufacturer_data.get("models", []):
                x, y, z = definition.get("build_volume", [None, None, None])
                defaults = {
                    "build_volume_x_mm": x,
                    "build_volume_y_mm": y,
                    "build_volume_z_mm": z,
                    "nozzle_mm": definition.get("nozzle_mm", 0.4),
                    "filament_diameter_mm": definition.get("filament_diameter_mm", 1.75),
                    "max_nozzle_temp_c": definition.get("max_nozzle_temp_c"),
                    "max_bed_temp_c": definition.get("max_bed_temp_c"),
                    "enclosed": bool(definition.get("enclosed")),
                    "multi_material_system": definition.get("multi_material_system", ""),
                    "max_multi_material_units": definition.get("max_multi_material_units"),
                    "features": definition.get("features", {}),
                    "source_url": definition.get("source_url", ""),
                }
                item, was_created = PrinterCatalogModel.objects.get_or_create(
                    manufacturer=maker,
                    name=definition["name"],
                    defaults=defaults,
                )
                models_created += int(was_created)
                if was_created:
                    continue

                changed = False
                for field, value in defaults.items():
                    current = getattr(item, field)
                    if current in (None, "", {}, []) and value not in (None, "", {}, []):
                        setattr(item, field, value)
                        changed = True
                if changed:
                    item.save()
                    models_enriched += 1

        self.stdout.write(
            self.style.SUCCESS(
                f"3D printer catalogue ready: {makers_created} manufacturers added, "
                f"{models_created} models added, {models_enriched} models enriched."
            )
        )
