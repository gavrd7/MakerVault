import io
import unittest
from unittest.mock import patch

from PIL import Image

from core.catalogue_images import (
    CatalogueImageError,
    sanitise_uploaded_image,
    validate_public_image_url,
)


class DummyUpload(io.BytesIO):
    def __init__(self, data):
        super().__init__(data)
        self.size = len(data)


class CatalogueImageTests(unittest.TestCase):
    @patch("core.catalogue_images._host_is_public", return_value=True)
    def test_public_https_url_is_allowed(self, _):
        self.assertEqual(
            validate_public_image_url("https://example.com/board.png"),
            "https://example.com/board.png",
        )

    @patch("core.catalogue_images._host_is_public", return_value=True)
    def test_http_image_url_is_rejected(self, _):
        with self.assertRaises(CatalogueImageError):
            validate_public_image_url("http://example.com/board.png")

    @patch("core.catalogue_images._host_is_public", return_value=False)
    def test_private_resolution_is_rejected(self, _):
        with self.assertRaises(CatalogueImageError):
            validate_public_image_url("https://example.com/board.png")

    def test_upload_is_sanitised_to_webp(self):
        source = io.BytesIO()
        Image.new("RGB", (64, 32), (20, 40, 60)).save(source, format="PNG")
        content, filename = sanitise_uploaded_image(DummyUpload(source.getvalue()), "test-board")
        self.assertTrue(filename.endswith(".webp"))
        image = Image.open(io.BytesIO(content.read()))
        self.assertEqual(image.format, "WEBP")
        self.assertEqual(image.size, (64, 32))


if __name__ == "__main__":
    unittest.main()
