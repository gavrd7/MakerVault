"""Personal spool imagery must never overwrite global catalogue artwork."""
from io import BytesIO
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.files.base import ContentFile
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings

from core.models import ReusableSpoolCatalogEntry, ReusableSpoolCatalogImageOverride, ReusableSpoolDesign


class PersonalSpoolImageTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.owner = get_user_model().objects.create_superuser(username="spool-image-a", email="a@example.test", password="test-password")
        cls.other = get_user_model().objects.create_superuser(username="spool-image-b", email="b@example.test", password="test-password")

    def setUp(self):
        self.client.force_login(self.owner)
        self.entry = ReusableSpoolCatalogEntry.objects.get(key="bambu-basic")

    def test_user_image_url_cached_without_changing_global_image(self):
        url = "https://images.example.org/my-empty-spool.png"
        with patch("core.reusable_spools.fetch_public_image", return_value=(
            ContentFile(b"fake-sanitised-image"), "sample.webp", url
        )) as fetch:
            response = self.client.post(
                "/api/printing/reusable-spool-manufacturers/bambu-basic/image/",
                {"url": url, "rights_confirmed": "true"},
            )
        self.assertEqual(response.status_code, 200, response.content)
        fetch.assert_called_once_with(url, "reusable-spool")
        self.assertTrue(ReusableSpoolCatalogImageOverride.objects.filter(owner=self.owner, catalog_entry=self.entry).exists())
        self.assertFalse(ReusableSpoolCatalogEntry.objects.get(pk=self.entry.pk).image)
        owner_row = next(r for r in self.client.get("/api/printing/reusable-spool-manufacturers/").json()["rows"] if r["key"] == self.entry.key)
        self.assertTrue(owner_row["image_personal"])
        self.client.force_login(self.other)
        other_row = next(r for r in self.client.get("/api/printing/reusable-spool-manufacturers/").json()["rows"] if r["key"] == self.entry.key)
        self.assertFalse(other_row["image_personal"])

    def test_reject_missing_permission_confirmation(self):
        response = self.client.post(
            "/api/printing/reusable-spool-manufacturers/bambu-basic/image/",
            {"url": "https://example.org/spool.png"},
        )
        self.assertEqual(response.status_code, 400)
        self.assertFalse(ReusableSpoolCatalogImageOverride.objects.exists())

    def test_owned_printed_design_supports_image_upload_and_reset(self):
        design = ReusableSpoolDesign.objects.create(owner=self.owner, name="My printed reel", design_type="printed")
        file = SimpleUploadedFile("reel.png", b"image-input", content_type="image/png")
        with patch("core.reusable_spools.sanitise_uploaded_image", return_value=(
            ContentFile(b"fake-sanitised-image"), "reel.webp"
        )):
            response = self.client.post(
                f"/api/printing/reusable-spool-designs/{design.id}/image/",
                {"image": file, "rights_confirmed": "true"},
            )
        self.assertEqual(response.status_code, 200, response.content)
        design.refresh_from_db()
        self.assertTrue(design.image)
        self.client.force_login(self.other)
        denied = self.client.delete(f"/api/printing/reusable-spool-designs/{design.id}/image/")
        self.assertEqual(denied.status_code, 404)
        self.client.force_login(self.owner)
        reset = self.client.delete(f"/api/printing/reusable-spool-designs/{design.id}/image/")
        self.assertEqual(reset.status_code, 200)
        design.refresh_from_db()
        self.assertFalse(design.image)
