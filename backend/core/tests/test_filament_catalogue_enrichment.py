from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase

from core.catalogue_coverage import catalogue_coverage_summary
from core.filament_catalogue import (
    apply_catalogue_match_to_filament,
    match_filament_catalogue_candidates,
    normalise_spoolmandb_row,
    refresh_imported_filament_products,
    unmatch_filament_catalogue,
)
from core.filament_technical_sources import parse_filament_technical_text
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


    @patch("core.filament_catalogue.get_spoolmandb_catalogue")
    def test_manual_filament_matching_ranks_identity_and_colour(self, catalogue):
        row = normalise_spoolmandb_row(self.spoolmandb_row())
        other = normalise_spoolmandb_row({
            **self.spoolmandb_row(),
            "id": "other-petg-white",
            "manufacturer": "Other",
            "name": "PETG White",
            "material": "PETG",
            "color_name": "White",
            "color_hex": "ffffff",
        })
        catalogue.return_value = [other, row]
        maker = FilamentManufacturer.objects.create(name="Example Filament")
        filament = FilamentProduct.objects.create(
            filament_manufacturer=maker,
            name="PLA Basic Black",
            material="PLA",
            color_name="Black",
            color_hex="#111111",
            diameter_mm="1.75",
        )

        matches = match_filament_catalogue_candidates(filament)

        self.assertEqual(matches[0]["external_id"], row["external_id"])
        self.assertGreater(matches[0]["match_score"], matches[1]["match_score"])
        self.assertIn("manufacturer", matches[0]["match_reasons"])
        self.assertIn("material", matches[0]["match_reasons"])

    @patch("core.filament_catalogue.enrich_filament_from_authoritative_sources")
    @patch("core.filament_catalogue.get_spoolmandb_item")
    def test_applying_manual_catalogue_match_fills_blanks_without_replacing_manual_identity(self, get_item, authoritative):
        row = normalise_spoolmandb_row(self.spoolmandb_row())
        get_item.return_value = row
        authoritative.return_value = {"checked_sources": 0, "changed_fields": [], "errors": 0}
        maker = FilamentManufacturer.objects.create(name="Example Filament")
        filament = FilamentProduct.objects.create(
            filament_manufacturer=maker,
            name="My local name",
            material="PLA",
            color_name="My black",
            color_hex="#101010",
            diameter_mm="1.75",
            density_g_cm3=None,
            nozzle_temp_min_c=None,
            bed_temp_min_c=None,
        )

        result = apply_catalogue_match_to_filament(filament, row["external_id"])
        filament.refresh_from_db()

        self.assertEqual(filament.name, "My local name")
        self.assertEqual(filament.color_name, "My black")
        self.assertEqual(filament.color_hex, "#101010")
        self.assertEqual(float(filament.density_g_cm3), 1.24)
        self.assertEqual(filament.nozzle_temp_min_c, 195)
        self.assertEqual(filament.bed_temp_min_c, 45)
        self.assertEqual(filament.profile_data["catalogue_provenance"]["external_id"], row["external_id"])
        authoritative.assert_called_once()
        self.assertIn("density_g_cm3", result["changed_fields"])

    @patch("core.filament_catalogue.enrich_filament_from_authoritative_sources")
    @patch("core.filament_catalogue.get_spoolmandb_item")
    def test_catalogue_match_can_be_unmatched_and_restores_previous_values(self, get_item, authoritative):
        row = normalise_spoolmandb_row(self.spoolmandb_row())
        get_item.return_value = row
        authoritative.return_value = {"checked_sources": 0, "changed_fields": [], "errors": 0}
        maker = FilamentManufacturer.objects.create(name="Example Filament")
        filament = FilamentProduct.objects.create(
            filament_manufacturer=maker,
            name="Local PLA",
            material="PLA",
            color_name="My Black",
            color_hex="#101010",
            diameter_mm="1.75",
            density_g_cm3=None,
            nominal_weight_g=None,
            profile_data={"local_note": "keep me"},
        )

        apply_catalogue_match_to_filament(filament, row["external_id"])
        filament.refresh_from_db()
        self.assertIsNotNone(filament.source_id)
        self.assertEqual(float(filament.density_g_cm3), 1.24)
        self.assertIn("catalogue_match_restore", filament.profile_data)

        result = unmatch_filament_catalogue(filament)
        filament.refresh_from_db()

        self.assertTrue(result["restored"])
        self.assertIsNone(filament.source_id)
        self.assertIsNone(filament.density_g_cm3)
        self.assertIsNone(filament.nominal_weight_g)
        self.assertEqual(filament.color_name, "My Black")
        self.assertEqual(filament.color_hex, "#101010")
        self.assertEqual(filament.profile_data, {"local_note": "keep me"})

    @patch("core.filament_catalogue.enrich_filament_from_authoritative_sources")
    @patch("core.filament_catalogue.get_spoolmandb_item")
    def test_catalogue_match_rounds_external_decimal_precision(self, get_item, authoritative):
        raw = {**self.spoolmandb_row(), "density": 1.23456, "weight": 1000.127}
        row = normalise_spoolmandb_row(raw)
        get_item.return_value = row
        authoritative.return_value = {"checked_sources": 0, "changed_fields": [], "errors": 0}
        maker = FilamentManufacturer.objects.create(name="Example Filament")
        filament = FilamentProduct.objects.create(
            filament_manufacturer=maker,
            name="Precision test",
            material="PLA",
            color_name="Black",
            color_hex="#111111",
            diameter_mm="1.75",
            density_g_cm3=None,
            nominal_weight_g=None,
        )

        apply_catalogue_match_to_filament(filament, row["external_id"])
        filament.refresh_from_db()

        self.assertEqual(str(filament.density_g_cm3), "1.235")
        self.assertEqual(str(filament.nominal_weight_g), "1000.13")

    @patch("core.filament_catalogue.enrich_filament_from_authoritative_sources")
    @patch("core.filament_catalogue.get_spoolmandb_item")
    def test_catalogue_match_ignores_unrelated_legacy_validation_errors(self, get_item, authoritative):
        row = normalise_spoolmandb_row(self.spoolmandb_row())
        get_item.return_value = row
        authoritative.return_value = {"checked_sources": 0, "changed_fields": [], "errors": 0}
        maker = FilamentManufacturer.objects.create(name="Example Filament")
        filament = FilamentProduct.objects.create(
            filament_manufacturer=maker,
            name="Legacy PLA",
            material="PLA",
            color_name="Black",
            color_hex="#111111",
            diameter_mm="1.75",
            finish="x" * 80,
            density_g_cm3=None,
        )

        result = apply_catalogue_match_to_filament(filament, row["external_id"])
        filament.refresh_from_db()

        self.assertEqual(filament.finish, "x" * 80)
        self.assertEqual(float(filament.density_g_cm3), 1.24)
        self.assertIn("density_g_cm3", result["changed_fields"])

    def test_manufacturer_technical_text_parser_extracts_print_settings(self):
        data = parse_filament_technical_text(
            "Density 1.24 g/cm3. Nozzle temperature 200-230 C. "
            "Bed temperature 50-65 C. Drying settings 55 C for 6 hours."
        )

        self.assertEqual(float(data["density_g_cm3"]), 1.24)
        self.assertEqual(data["nozzle_temp_min_c"], 200)
        self.assertEqual(data["nozzle_temp_max_c"], 230)
        self.assertEqual(data["bed_temp_min_c"], 50)
        self.assertEqual(data["bed_temp_max_c"], 65)
        self.assertEqual(data["drying_temp_c"], 55)
        self.assertEqual(float(data["drying_time_hours"]), 6.0)

    def test_filament_image_delete_uses_image_metadata_and_opts_out(self):
        user = get_user_model().objects.create_superuser(
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
