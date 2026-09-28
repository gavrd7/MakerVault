import unittest
from unittest.mock import Mock, patch

from core.catalogue_image_sources import (
    _board_image_queries,
    _commons_license_allowed,
    _component_image_queries,
    _espboards_slug_candidates,
    _openverse_license_name,
    _printer_image_queries,
    search_openverse,
    search_wikimedia_commons,
)


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

    def test_printer_image_query_disambiguates_short_model_names(self):
        queries = _printer_image_queries(DummyPrinterModel())
        self.assertEqual(queries[0], "Creality K2 3D printer")
        self.assertIn("Creality K2 printer", queries)

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


if __name__ == "__main__":
    unittest.main()
