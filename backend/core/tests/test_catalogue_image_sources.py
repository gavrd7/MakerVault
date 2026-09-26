import unittest
from unittest.mock import Mock, patch

from core.catalogue_image_sources import (
    _espboards_slug_candidates,
    search_wikimedia_commons,
)


class DummyManufacturer:
    name = "Seeed Studio"


class DummyBoard:
    name = "XIAO ESP32C3"
    manufacturer = DummyManufacturer()


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


if __name__ == "__main__":
    unittest.main()
