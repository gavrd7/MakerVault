from unittest.mock import patch

from django.test import TestCase

from core.catalogue_coverage import catalogue_coverage_summary
from core.filament_catalogue import (
    normalise_spoolmandb_row,
    refresh_imported_filament_products,
)
from core.models import CatalogSource, FilamentManufacturer, FilamentProduct


class FilamentCatalogueEnrichmentTests(TestCase):
    def spoolmandb_row(self):
        return {
            "id": "example-pla-black-175-1000",
            "manufacturer": "Example Filament",
            "name": "PLA Basic Black",
            "material": "PLA",
            "density": 1.24,
            "diameter": 1.75,
            "weight": 1000,
            "spool_weight": 220,
            "spool_type": "cardboard",
            "is_refill": False,
            "color_name": "Black",
            "color_hex": "111111",
            "extruder_temp_range": [195, 220],
            "bed_temp_range": [45, 60],
            "country_of_origin": "GB",
            "product_url": "https://example.com/products/pla-basic",
            "tds_url": "https://example.com/pla-basic-tds.pdf",
            "sds_url": "https://example.com/pla-basic-sds.pdf",
            "codes": ["PLA-BLK"],
            "eans": ["1234567890123"],
        }

    def test_normalise_spoolmandb_row_retains_richer_provenance(self):
        item = normalise_spoolmandb_row(self.spoolmandb_row())

        self.assertEqual(item["spool_type"], "cardboard")
        self.assertEqual(item["country_of_origin"], "GB")
        self.assertEqual(item["product_url"], "https://example.com/products/pla-basic")
        self.assertEqual(item["tds_url"], "https://example.com/pla-basic-tds.pdf")
        self.assertEqual(item["codes"], ["PLA-BLK"])
        self.assertEqual(item["eans"], ["1234567890123"])

    @patch("core.filament_catalogue.get_spoolmandb_catalogue")
    def test_refresh_fills_blanks_without_overwriting_user_edits(self, catalogue):
        upstream = normalise_spoolmandb_row(self.spoolmandb_row())
        catalogue.return_value = [upstream]

        maker = FilamentManufacturer.objects.create(name="Example Filament")
        source = CatalogSource.objects.create(
            name="SpoolmanDB example",
            source_type="spoolmandb",
            external_id=upstream["external_id"],
            url=upstream["source_url"],
        )
        filament = FilamentProduct.objects.create(
            filament_manufacturer=maker,
            source=source,
            name="My corrected PLA name",
            material="PLA",
            color_name="Black",
            color_hex="#111111",
            diameter_mm="1.75",
            density_g_cm3=None,
            nominal_weight_g=None,
            nozzle_temp_min_c=None,
            nozzle_temp_max_c=None,
            bed_temp_min_c=None,
            bed_temp_max_c=None,
        )

        result = refresh_imported_filament_products(force_catalogue=True)
        filament.refresh_from_db()

        self.assertEqual(result["updated"], 1)
        self.assertEqual(filament.name, "My corrected PLA name")
        self.assertEqual(float(filament.density_g_cm3), 1.24)
        self.assertEqual(float(filament.nominal_weight_g), 1000.0)
        self.assertEqual(filament.nozzle_temp_min_c, 195)
        self.assertEqual(filament.bed_temp_max_c, 60)
        provenance = filament.profile_data["catalogue_provenance"]
        self.assertEqual(provenance["product_url"], "https://example.com/products/pla-basic")
        self.assertEqual(provenance["country_of_origin"], "GB")

    def test_filament_image_delete_uses_image_metadata_and_opts_out(self):
        user = __import__("django.contrib.auth", fromlist=["get_user_model"]).get_user_model().objects.create_superuser(
            username="filament-image-admin",
            email="filament-image@example.com",
            password="test-password",
        )
        self.client.force_login(user)
        maker = FilamentManufacturer.objects.create(name="Image Filament")
        filament = FilamentProduct.objects.create(
            filament_manufacturer=maker,
            name="PLA Image Test",
            material="PLA",
            diameter_mm="1.75",
            image_metadata={
                "external_image_url": "https://example.com/filament.jpg",
                "image_source_page": "https://example.com/products/filament",
                "image_source_provider": "Example official",
            },
        )

        response = self.client.delete(f"/api/printing/filaments/{filament.id}/image/")
        self.assertEqual(response.status_code, 200, response.content)

        filament.refresh_from_db()
        self.assertFalse(filament.image)
        self.assertNotIn("external_image_url", filament.image_metadata)
        self.assertTrue(filament.image_metadata["auto_image_opt_out"])
        self.assertEqual(response.json()["filament"]["image"], "")

    def test_coverage_counts_remote_filament_image_and_rich_metadata(self):
        maker = FilamentManufacturer.objects.create(name="Example Filament")
        FilamentProduct.objects.create(
            filament_manufacturer=maker,
            name="PLA Basic Black",
            material="PLA",
            color_name="Black",
            color_hex="#111111",
            diameter_mm="1.75",
            density_g_cm3="1.240",
            nominal_weight_g="1000",
            nozzle_temp_min_c=195,
            nozzle_temp_max_c=220,
            bed_temp_min_c=45,
            bed_temp_max_c=60,
            image_metadata={
                "external_image_url": "https://example.com/pla.jpg",
                "image_source_page": "https://example.com/products/pla",
            },
            profile_data={
                "catalogue_provenance": {
                    "product_url": "https://example.com/products/pla",
                }
            },
        )

        filament = next(
            item for item in catalogue_coverage_summary()["catalogues"]
            if item["key"] == "filaments"
        )
        metrics = {item["key"]: item for item in filament["metrics"]}

        self.assertEqual(metrics["images"]["percent"], 100.0)
        self.assertEqual(metrics["density"]["percent"], 100.0)
        self.assertEqual(metrics["weight"]["percent"], 100.0)
        self.assertEqual(metrics["sources"]["percent"], 100.0)
