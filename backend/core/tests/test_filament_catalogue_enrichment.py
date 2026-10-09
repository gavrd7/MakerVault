from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase

from core.catalogue_coverage import catalogue_coverage_summary
from core.filament_catalogue import (
    apply_catalogue_match_to_filament,
    FilamentCatalogueError,
    get_supplemental_filament_catalogue,
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

    def test_supplemental_catalogue_contains_verified_gap_entries(self):
        rows = get_supplemental_filament_catalogue()
        ids = {row["external_id"] for row in rows}

        self.assertIn("makervault-esun-tpe83a-black-175-1000", ids)
        self.assertIn("makervault-eryone-asa-high-speed-black-175-1000", ids)

    @patch("core.filament_catalogue.get_spoolmandb_catalogue", return_value=[])
    def test_supplemental_catalogue_aliases_improve_matching(self, _catalogue):
        maker = FilamentManufacturer.objects.create(name="Eryone")
        filament = FilamentProduct.objects.create(
            filament_manufacturer=maker,
            name="Hyper ASA Black",
            material="ASA",
            color_name="Black",
            diameter_mm="1.75",
        )

        matches = match_filament_catalogue_candidates(filament)

        self.assertTrue(matches)
        self.assertEqual(matches[0]["external_id"], "makervault-eryone-asa-high-speed-black-175-1000")
        self.assertIn("product name", matches[0]["match_reasons"])
        self.assertGreaterEqual(matches[0]["match_score"], 80)

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
            transparency="legacy",
            density_g_cm3=None,
        )

        result = apply_catalogue_match_to_filament(filament, row["external_id"])
        filament.refresh_from_db()

        self.assertEqual(filament.transparency, "legacy")
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


class FilamentContinuationTaskTests(TestCase):
    @patch("core.tasks.backup_in_progress", return_value=False)
    @patch("core.tasks.refresh_imported_filament_products")
    def test_continue_only_when_more_rows_exist(self, refresh, _backup):
        from core.tasks import enrich_filament_catalogue_task

        refresh.return_value = {
            "status": "limit-reached", "checked": 80, "updated": 2,
            "next_cursor": "00000000-0000-0000-0000-000000000080",
        }
        with patch.object(enrich_filament_catalogue_task, "apply_async") as queue:
            result = enrich_filament_catalogue_task(force_catalogue=True)
            queue.assert_called_once_with(
                kwargs={
                    "force_catalogue": False,
                    "limit": 80,
                    "cursor": "00000000-0000-0000-0000-000000000080",
                },
                countdown=5,
            )
            refresh.return_value = {
                "status": "complete", "checked": 23,
                "updated": 0, "next_cursor": None,
            }
            enrich_filament_catalogue_task(
                limit=80, cursor=result["next_cursor"],
            )
            self.assertEqual(queue.call_count, 1)


    @patch("core.tasks.backup_in_progress", return_value=False)
    @patch("core.tasks.refresh_imported_filament_products")
    def test_new_scheduled_task_resumes_after_lost_celery_continuation(self, refresh, _backup):
        from core.models import CatalogueMaintenanceSettings
        from core.tasks import enrich_filament_catalogue_task
        refresh.side_effect = [
            {"status": "limit-reached", "checked": 80, "next_cursor": "cursor-80"},
            {"status": "complete", "checked": 23, "next_cursor": None},
        ]
        with patch.object(enrich_filament_catalogue_task, "apply_async") as queue:
            enrich_filament_catalogue_task()
            checkpoint = CatalogueMaintenanceSettings.objects.get(singleton_key=1)
            self.assertEqual(checkpoint.filament_enrichment_cursor, "cursor-80")
            # No explicit cursor: scheduled job recovers the saved progress.
            enrich_filament_catalogue_task()
            self.assertEqual(refresh.call_args.kwargs["cursor"], "cursor-80")
            checkpoint.refresh_from_db()
            self.assertEqual(checkpoint.filament_enrichment_cursor, "")
            self.assertEqual(queue.call_count, 1)

    @patch("core.tasks.backup_in_progress", return_value=False)
    @patch("core.tasks.refresh_imported_filament_products",
           side_effect=FilamentCatalogueError("upstream unavailable"))
    def test_failed_refresh_keeps_saved_checkpoint(self, refresh, _backup):
        from core.models import CatalogueMaintenanceSettings
        from core.tasks import enrich_filament_catalogue_task
        checkpoint, _ = CatalogueMaintenanceSettings.objects.get_or_create(singleton_key=1)
        checkpoint.filament_enrichment_cursor = "saved-cursor"
        checkpoint.save(update_fields=["filament_enrichment_cursor"])
        result = enrich_filament_catalogue_task()
        self.assertEqual(result["status"], "error")
        self.assertEqual(refresh.call_args.kwargs["cursor"], "saved-cursor")
        checkpoint.refresh_from_db()
        self.assertEqual(checkpoint.filament_enrichment_cursor, "saved-cursor")

    @patch("core.filament_catalogue.enrich_filament_from_authoritative_sources",
           return_value={"changed_fields": []})
    @patch("core.filament_catalogue.get_spoolmandb_catalogue")
    def test_refresh_all_103_imported_products_in_two_batches(self, upstream, _authoritative):
        import uuid

        source_ids = []
        records = []
        for index in range(103):
            external_id = f"batch-fixture-{index:03d}"
            source_ids.append(external_id)
            source = CatalogSource.objects.create(
                source_type="spoolmandb",
                name=f"Fixture {index}",
                url=f"https://example.com/filament/{index}",
                external_id=external_id,
            )
            records.append(FilamentProduct(
                id=uuid.UUID(int=index + 1),
                source=source,
                name=f"Fixture PLA {index}",
                material="PLA",
                color_name="Existing colour",
            ))
        FilamentProduct.objects.bulk_create(records)
        upstream.return_value = [
            {"external_id": external_id, "color_name": "Upstream colour",
             "density_g_cm3": 1.24, "raw": {}, "source_license": "MIT"}
            for external_id in source_ids
        ]

        # CI can run with a cache backend unlike the Debian test server.
        # Use an isolated, deterministic shared cache to test sweep reuse.
        snapshot = {}
        class FakeCache:
            def get(self, key):
                return snapshot.get(key)
            def set(self, key, value, timeout=None):
                snapshot[key] = value
            def delete(self, key):
                snapshot.pop(key, None)

        with patch("core.filament_catalogue.cache", FakeCache()):
            first = refresh_imported_filament_products(limit=80)
            second = refresh_imported_filament_products(limit=80, cursor=first["next_cursor"])
        self.assertEqual((first["status"], first["checked"]), ("limit-reached", 80))
        self.assertEqual((second["status"], second["checked"]), ("complete", 23))
        # A 103-record sweep must not refetch the same upstream catalogue
        # for the second 23-record batch.
        upstream.assert_called_once()
        self.assertIsNone(second["next_cursor"])
        self.assertEqual(
            FilamentProduct.objects.filter(source__source_type="spoolmandb",
                                          density_g_cm3="1.24").count(), 103,
        )
        self.assertEqual(
            FilamentProduct.objects.filter(color_name="Existing colour").count(), 103,
        )

    @patch("core.tasks.backup_in_progress", return_value=True)
    @patch("core.tasks.refresh_imported_filament_products")
    def test_does_not_refresh_during_backup(self, refresh, _backup):
        from core.tasks import enrich_filament_catalogue_task

        self.assertEqual(
            enrich_filament_catalogue_task()["status"], "backup-in-progress",
        )
        refresh.assert_not_called()


class AutomaticStarterFilamentTests(TestCase):
    @patch("core.filament_catalogue.get_spoolmandb_catalogue")
    def test_populates_empty_catalogue_and_is_idempotent(self, upstream):
        from core.filament_catalogue import seed_starter_filament_catalogue
        upstream.return_value = [
            {
                "external_id": f"starter-{i}", "manufacturer": f"Maker {i}",
                "name": f"PLA Variant {i}", "material": "PLA",
                "color_name": "Black", "color_hex": "#111111",
                "color_hexes": ["#111111"], "raw": {},
                "source_url": "https://donkie.github.io/SpoolmanDB/",
            }
            for i in range(125)
        ]
        first = seed_starter_filament_catalogue()
        self.assertEqual(first["created"], 120)
        self.assertEqual(FilamentProduct.objects.count(), 120)
        second = seed_starter_filament_catalogue()
        self.assertEqual(second["created"], 0)
        self.assertEqual(FilamentProduct.objects.count(), 120)

    @patch("core.filament_catalogue.get_spoolmandb_catalogue")
    def test_starter_does_not_change_existing_product(self, upstream):
        from core.filament_catalogue import seed_starter_filament_catalogue
        upstream.return_value = [{
            "external_id": "starter-existing", "manufacturer": "Fixture",
            "name": "PLA Black", "material": "PLA",
            "color_name": "Black", "color_hex": "#111111",
            "color_hexes": ["#111111"], "raw": {},
        }]
        source = CatalogSource.objects.create(
            name="Fixture source", source_type="spoolmandb",
            external_id="starter-existing", url="https://example.com",
        )
        existing = FilamentProduct.objects.create(
            source=source, name="Custom PLA", material="PLA", color_name="My colour",
        )
        outcome = seed_starter_filament_catalogue()
        existing.refresh_from_db()
        self.assertEqual(outcome["created"], 0)
        self.assertEqual(existing.name, "Custom PLA")
        self.assertEqual(existing.color_name, "My colour")

    @patch("core.tasks.backup_in_progress", return_value=True)
    @patch("core.tasks.seed_starter_filament_catalogue")
    def test_starter_pauses_for_backup(self, seed, _backup):
        from core.tasks import seed_starter_filament_catalogue_task
        self.assertEqual(seed_starter_filament_catalogue_task()["status"], "backup-in-progress")
        seed.assert_not_called()

    @patch("core.tasks.backup_in_progress", return_value=False)
    @patch("core.tasks.enrich_filament_catalogue_task.delay")
    @patch("core.tasks.seed_starter_filament_catalogue",
           return_value={"status": "complete", "created": 15})
    def test_starter_queues_refresh_after_seeding(self, seed, refresh, _backup):
        from core.tasks import seed_starter_filament_catalogue_task

        self.assertEqual(seed_starter_filament_catalogue_task()["created"], 15)
        seed.assert_called_once()
        refresh.assert_called_once_with(force_catalogue=False)
