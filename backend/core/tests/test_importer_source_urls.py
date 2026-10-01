from unittest.mock import patch

from django.test import SimpleTestCase

from core.importers import (
    ImporterError,
    validate_catalogue_source_url,
    validate_import_url,
)


class CatalogueSourceURLValidationTests(SimpleTestCase):
    @patch("core.importers._host_is_public", return_value=True)
    def test_catalogue_source_allows_known_manufacturer_subdomains(self, _public):
        safe = validate_catalogue_source_url(
            "https://docs.beagleboard.org/latest/boards/beagleplay/index.html"
        )
        self.assertEqual(safe.host, "docs.beagleboard.org")

    @patch("core.importers._host_is_public", return_value=True)
    def test_catalogue_source_allows_printer_manufacturer_hosts(self, _public):
        for url in (
            "https://www.creality.com/products/example",
            "https://bambulab.com/en/example",
            "https://qidi3d.com/pages/example",
        ):
            with self.subTest(url=url):
                self.assertTrue(validate_catalogue_source_url(url).host)

    @patch("core.importers._host_is_public", return_value=True)
    def test_catalogue_source_allows_curated_github_pages(self, _public):
        safe = validate_catalogue_source_url(
            "https://github.com/witnessmenow/ESP32-Cheap-Yellow-Display"
        )
        self.assertEqual(safe.host, "github.com")

    @patch("core.importers._host_is_public", return_value=True)
    def test_catalogue_source_rejects_unlisted_hosts(self, _public):
        with self.assertRaises(ImporterError):
            validate_catalogue_source_url("https://example.com/product")

    @patch("core.importers._host_is_public", return_value=True)
    def test_user_board_import_remains_espboards_only(self, _public):
        with self.assertRaises(ImporterError):
            validate_import_url("https://docs.beagleboard.org/latest/boards/beagleplay/index.html")
        with self.assertRaises(ImporterError):
            validate_import_url("https://github.com/witnessmenow/ESP32-Cheap-Yellow-Display")
        safe = validate_import_url("https://www.espboards.dev/esp32/example/")
        self.assertEqual(safe.host, "www.espboards.dev")
