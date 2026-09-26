import unittest

from core.catalogue_enrichment import _slug_candidates, _tokens


class DummyManufacturer:
    name = "Seeed Studio"


class DummyBoard:
    name = "XIAO ESP32C6"
    manufacturer = DummyManufacturer()


class CatalogueEnrichmentTests(unittest.TestCase):
    def test_slug_candidates_include_plain_board_name(self):
        self.assertIn("xiao-esp32c6", _slug_candidates(DummyBoard()))

    def test_token_matching_ignores_generic_words(self):
        self.assertEqual(_tokens("Generic ESP32-S3 Super Mini board"), {"esp32", "s3", "super"})
        self.assertTrue({"esp32", "c6"}.issubset(_tokens("Seeed Studio XIAO ESP32C6")))


if __name__ == "__main__":
    unittest.main()
