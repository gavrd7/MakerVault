"""Full catalogue population is additive, bounded and colour-aware."""
from unittest.mock import patch

from django.test import TestCase

from core.filament_catalogue import populate_missing_filament_variants
from core.models import FilamentProduct


def sample(external_id, colour):
    return {
        "external_id": external_id,
        "manufacturer": "Sunlu",
        "name": "High Speed Matte PETG",
        "material": "PETG",
        "color_name": colour,
        "color_hex": "#ffbf49" if colour == "Yellow" else "#f4a9c7",
        "color_hexes": [],
        "source_url": "https://example.org/catalogue",
        "raw": {"id": external_id},
    }


class FilamentVariantPopulationTests(TestCase):
    @patch("core.filament_catalogue.get_filament_catalogue")
    def test_creates_missing_colours_and_is_idempotent(self, upstream):
        upstream.return_value = [sample("sunlu-petg-yellow", "Yellow"), sample("sunlu-petg-pink", "Pink")]

        first = populate_missing_filament_variants(limit=1)
        self.assertEqual(first["status"], "limit-reached")
        self.assertEqual(first["created"], 1)
        self.assertEqual(FilamentProduct.objects.count(), 1)

        second = populate_missing_filament_variants(limit=1)
        self.assertEqual(second["status"], "complete")
        self.assertEqual(second["created"], 1)
        self.assertEqual(
            set(FilamentProduct.objects.values_list("color_name", flat=True)),
            {"Yellow", "Pink"},
        )

        third = populate_missing_filament_variants(limit=1)
        self.assertEqual(third["created"], 0)
        self.assertEqual(FilamentProduct.objects.count(), 2)

    @patch("core.filament_catalogue.get_filament_catalogue")
    def test_different_source_ids_same_variant_do_not_make_duplicates(self, upstream):
        upstream.return_value = [
            sample("sunlu-yellow-source-1", "Yellow"),
            sample("sunlu-yellow-source-2", "Yellow"),
            sample("sunlu-pink-source-1", "Pink"),
        ]
        result = populate_missing_filament_variants(limit=20)
        self.assertEqual(result["created"], 2)
        self.assertEqual(result["skipped_duplicates"], 1)
        self.assertEqual(FilamentProduct.objects.count(), 2)
        result = populate_missing_filament_variants(limit=20)
        self.assertEqual(result["created"], 0)

    @patch("core.filament_catalogue.get_filament_catalogue")
    def test_does_not_overwrite_manual_product_changes(self, upstream):
        upstream.return_value = [sample("sunlu-petg-yellow", "Yellow")]
        populate_missing_filament_variants()
        product = FilamentProduct.objects.get()
        product.color_name = "My corrected yellow"
        product.save(update_fields=["color_name"])
        populate_missing_filament_variants()
        product.refresh_from_db()
        self.assertEqual(product.color_name, "My corrected yellow")
        self.assertEqual(FilamentProduct.objects.count(), 1)
