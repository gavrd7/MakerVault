import unittest
from unittest.mock import Mock, patch

from django.test import TestCase, override_settings

from core.catalogue_image_sources import (
    _board_image_queries,
    _commons_license_allowed,
    _component_image_queries,
    _espboards_slug_candidates,
    _openverse_license_name,
    _printer_image_queries,
    _printer_multi_material_image_queries,
    find_source_page_image,
    run_catalogue_image_seed,
    search_openverse,
    search_wikimedia_commons,
)
from core.models import BoardModel, ComponentCategory, ComponentModel, PrinterCatalogModel, PrinterManufacturer


class DummyManufacturer:
    name = "Seeed Studio"


class DummyBoard:
    name = "XIAO ESP32C3"
    manufacturer = DummyManufacturer()




class DummyGenericManufacturer:
    name = "Generic"


class DummyGenericBoard:
    name = "ESP32 C3 Super Mini"
    mcu = "ESP32-C3"
    manufacturer = DummyGenericManufacturer()


class DummyComponent:
    name = "BME280 temperature/humidity/pressure sensor"
    part_number = "BME280"
    specifications = {"type": "environment"}


class DummyPrinterManufacturer:
    name = "Creality"


class DummyPrinterModel:
    name = "K2"
    manufacturer = DummyPrinterManufacturer()
    multi_material_system = "creality_cfs"
    MULTI_MATERIAL_SYSTEMS = [
        ("", "None / unknown"),
        ("creality_cfs", "Creality CFS"),
    ]


class CatalogueImageSourceTests(unittest.TestCase):
    def test_espboards_slug_candidates_are_stable(self):
        slugs = _espboards_slug_candidates(DummyBoard())
        self.assertIn("xiao-esp32c3", slugs)

    @patch("core.catalogue_image_sources.requests.get")
    def test_commons_search_filters_and_returns_free_licensed_raster(self, get):
        response = Mock()
        response.raise_for_status.return_value = None
        response.json.return_value = {
            "query": {
                "pages": [
                    {
                        "title": "File:BME280 sensor module.jpg",
                        "imageinfo": [{
                            "mime": "image/jpeg",
                            "thumburl": "https://upload.wikimedia.org/example.jpg",
                            "descriptionurl": "https://commons.wikimedia.org/wiki/File:BME280_sensor_module.jpg",
                            "extmetadata": {
                                "LicenseShortName": {"value": "CC BY-SA 4.0"},
                                "Artist": {"value": "Example Author"},
                            },
                        }],
                    }
                ]
            }
        }
        get.return_value = response
        candidate = search_wikimedia_commons("BME280 sensor module", minimum_score=0.1)
        self.assertIsNotNone(candidate)
        self.assertEqual(candidate.provider, "Wikimedia Commons")
        self.assertEqual(candidate.license_name, "CC BY-SA 4.0")
        self.assertEqual(candidate.author, "Example Author")

    @patch("core.catalogue_image_sources.requests.get")
    def test_commons_search_rejects_non_free_license(self, get):
        response = Mock()
        response.raise_for_status.return_value = None
        response.json.return_value = {
            "query": {
                "pages": [{
                    "title": "File:Example.jpg",
                    "imageinfo": [{
                        "mime": "image/jpeg",
                        "url": "https://upload.wikimedia.org/example.jpg",
                        "descriptionurl": "https://commons.wikimedia.org/wiki/File:Example.jpg",
                        "extmetadata": {"LicenseShortName": {"value": "All rights reserved"}},
                    }],
                }]
            }
        }
        get.return_value = response
        self.assertIsNone(search_wikimedia_commons("Example", minimum_score=0.0))

    def test_commons_license_filter_rejects_noncommercial_and_nd(self):
        self.assertTrue(_commons_license_allowed("CC BY 4.0"))
        self.assertTrue(_commons_license_allowed("CC BY-SA 4.0"))
        self.assertTrue(_commons_license_allowed("CC0 1.0"))
        self.assertTrue(_commons_license_allowed("Public domain"))
        self.assertFalse(_commons_license_allowed("CC BY-NC 4.0"))
        self.assertFalse(_commons_license_allowed("CC BY-ND 4.0"))
        self.assertFalse(_commons_license_allowed("CC BY-NC-SA 4.0"))


    def test_query_generation_prefers_exact_names(self):
        self.assertEqual(_board_image_queries(DummyGenericBoard())[0], "ESP32 C3 Super Mini")
        queries = _component_image_queries(DummyComponent())
        self.assertEqual(queries[0], "BME280 module")
        self.assertIn("BME280", queries)

    def test_component_query_preserves_slide_potentiometer_form_factor(self):
        component = DummyComponent()
        component.name = "10k slide potentiometer"
        component.part_number = ""
        component.specifications = {"type": "potentiometer", "value": "10 kΩ"}
        queries = _component_image_queries(component)
        self.assertEqual(queries[0], "10k slide potentiometer")
        self.assertIn("10k slide potentiometer linear slider", queries)
        self.assertIn("slide potentiometer electronics", queries)

    @patch("core.catalogue_image_sources.fetch_import_html")
    def test_source_page_remote_image_uses_opengraph_without_caching(self, fetch_html):
        class Source:
            url = "https://vendor.example/products/widget"

        component = DummyComponent()
        component.source = Source()
        fetch_html.return_value = (
            "https://vendor.example/products/widget",
            '<html><head><meta property="og:image" content="/media/widget.jpg"></head></html>',
        )
        found = find_source_page_image(component)
        self.assertEqual(found["external_image_url"], "https://vendor.example/media/widget.jpg")
        self.assertEqual(found["image_source_provider"], "vendor.example")
        self.assertEqual(found["image_source_type"], "source-page-remote")

    @patch("core.catalogue_image_sources.fetch_import_html")
    def test_source_pages_try_manufacturer_before_generic(self, fetch_html):
        class Source:
            url = "https://example.net/widget"
            source_type = "generic"
            name = "Generic source"

        component = DummyComponent()
        component.source = Source()
        component.specifications = {
            "type": "environment",
            "reference_url": "https://www.adafruit.com/product/1234",
            "reference_provider": "Adafruit",
        }

        fetch_html.return_value = (
            "https://www.adafruit.com/product/1234",
            '<html><head><meta property="og:image" content="https://cdn.example/official.jpg"></head></html>',
        )
        found = find_source_page_image(component)
        self.assertEqual(found["image_source_tier"], "manufacturer")
        self.assertEqual(found["image_source_priority"], 10)
        self.assertEqual(fetch_html.call_args.args[0], "https://www.adafruit.com/product/1234")

    def test_printer_image_query_disambiguates_short_model_names(self):
        queries = _printer_image_queries(DummyPrinterModel())
        self.assertEqual(queries[0], "Creality K2")
        self.assertIn("Creality K2 3D printer", queries)
        self.assertIn("Creality K2 printer", queries)

    def test_printer_combo_image_queries_include_combo_and_system(self):
        queries = _printer_multi_material_image_queries(DummyPrinterModel())
        self.assertEqual(queries[0], "Creality K2 Combo 3D printer")
        self.assertIn("Creality K2 Creality CFS 3D printer", queries)

    def test_openverse_license_mapping_is_restrictive(self):
        self.assertEqual(_openverse_license_name("by", "4.0"), "CC BY 4.0")
        self.assertEqual(_openverse_license_name("by-sa", "4.0"), "CC BY-SA 4.0")
        self.assertEqual(_openverse_license_name("cc0", "1.0"), "CC0 1.0")
        self.assertEqual(_openverse_license_name("pdm", "1.0"), "Public Domain 1.0")
        self.assertEqual(_openverse_license_name("by-nc", "4.0"), "")

    @patch("core.catalogue_image_sources.requests.get")
    def test_openverse_returns_attributed_open_image(self, get):
        response = Mock()
        response.raise_for_status.return_value = None
        response.json.return_value = {
            "results": [{
                "title": "BME280 module breakout",
                "thumbnail": "https://example.org/thumb.jpg",
                "foreign_landing_url": "https://example.org/work",
                "license": "by-sa",
                "license_version": "4.0",
                "creator": "Example Creator",
                "source": "wikimedia",
                "tags": [],
            }]
        }
        get.return_value = response
        candidate = search_openverse("BME280 module", minimum_score=0.1)
        self.assertIsNotNone(candidate)
        self.assertEqual(candidate.license_name, "CC BY-SA 4.0")
        self.assertEqual(candidate.author, "Example Creator")
        self.assertTrue(candidate.provider.startswith("Openverse /"))



class CatalogueImagePriorityTests(TestCase):
    def setUp(self):
        self.printer_maker = PrinterManufacturer.objects.create(name="Image Test Printers")
        self.printer = PrinterCatalogModel.objects.create(
            manufacturer=self.printer_maker,
            name="Exact Model 42",
        )
        self.board = BoardModel.objects.create(name="Image Test Board")
        category = ComponentCategory.objects.create(name="Image Test Components", slug="image-test-components")
        self.component = ComponentModel.objects.create(
            category=category,
            name="Image Test Component",
            specifications={"type": "sensor"},
        )

    @override_settings(
        CATALOGUE_IMAGE_MAX_PER_RUN=1,
        CATALOGUE_IMAGE_RETRY_DAYS=1,
        CATALOGUE_IMAGE_WIKIMEDIA=True,
        CATALOGUE_IMAGE_OPENVERSE=True,
    )
    @patch("core.catalogue_image_sources.cache.delete")
    @patch("core.catalogue_image_sources.cache.add", return_value=True)
    @patch("core.catalogue_image_sources.cache_candidate")
    @patch("core.catalogue_image_sources._search_open_media_with_diagnostics")
    def test_targeted_printer_pass_does_not_spend_limit_on_other_catalogues(
        self,
        search,
        cache_candidate,
        cache_add,
        cache_delete,
    ):
        from core.catalogue_image_sources import ImageCandidate

        candidate = ImageCandidate(
            image_url="https://upload.wikimedia.org/example.jpg",
            source_page_url="https://commons.wikimedia.org/example",
            provider="Wikimedia Commons",
            license_name="CC BY-SA 4.0",
            query="Image Test Printers Exact Model 42",
        )
        search.return_value = (
            candidate,
            {"attempts": [{"provider": "Wikimedia Commons", "query": candidate.query, "matched": True}]},
        )

        result = run_catalogue_image_seed(
            limit=1,
            force_retry=True,
            kinds=["printers"],
        )

        self.assertEqual(result["status"], "complete")
        self.assertEqual(result["processed"], 1)
        self.assertEqual(result["by_kind"]["printers"]["cached"], 1)
        self.assertEqual(result["order"], ["printers"])
        cache_candidate.assert_called_once()
        cached_obj = cache_candidate.call_args.args[0]
        self.assertEqual(cached_obj.pk, self.printer.pk)
        cache_add.assert_called_once()
        cache_delete.assert_called_once()

    @override_settings(
        CATALOGUE_IMAGE_MAX_PER_RUN=1,
        CATALOGUE_IMAGE_RETRY_DAYS=1,
        CATALOGUE_IMAGE_WIKIMEDIA=True,
        CATALOGUE_IMAGE_OPENVERSE=True,
    )
    @patch("core.catalogue_image_sources.cache.delete")
    @patch("core.catalogue_image_sources.cache.add", return_value=True)
    @patch("core.catalogue_image_sources.resolve_catalogue_image")
    @patch("core.catalogue_image_sources.find_source_page_image")
    def test_manufacturer_remote_image_precedes_open_media(
        self,
        source_image,
        open_media,
        cache_add,
        cache_delete,
    ):
        self.component.specifications = {
            **self.component.specifications,
            "reference_url": "https://www.adafruit.com/product/999",
        }
        self.component.save(update_fields=["specifications", "updated_at"])
        source_image.return_value = {
            "external_image_url": "https://cdn.example/official.jpg",
            "image_source_page": "https://www.adafruit.com/product/999",
            "image_source_provider": "Adafruit",
            "image_source_type": "source-page-remote",
            "image_source_tier": "manufacturer",
            "image_source_priority": 10,
            "image_license": "",
            "image_author": "",
        }

        result = run_catalogue_image_seed(
            limit=1,
            force_retry=True,
            kinds=["components"],
        )

        self.assertEqual(result["remote"], 1)
        self.assertEqual(result["by_kind"]["components"]["remote"], 1)
        open_media.assert_not_called()
        self.component.refresh_from_db()
        self.assertEqual(
            self.component.specifications["external_image_url"],
            "https://cdn.example/official.jpg",
        )
        self.assertEqual(
            self.component.specifications["source_trace"][-1]["tier"],
            "manufacturer",
        )
        cache_add.assert_called_once()
        cache_delete.assert_called_once()

    @override_settings(
        CATALOGUE_IMAGE_MAX_PER_RUN=0,
        CATALOGUE_IMAGE_RETRY_DAYS=1,
        CATALOGUE_IMAGE_WIKIMEDIA=True,
        CATALOGUE_IMAGE_OPENVERSE=True,
    )
    def test_unknown_target_kind_is_rejected(self):
        with self.assertRaises(ValueError):
            run_catalogue_image_seed(kinds=["not-a-catalogue"])


if __name__ == "__main__":
    unittest.main()
