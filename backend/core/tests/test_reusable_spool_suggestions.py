import json
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase

from core.models import ReusableSpoolCatalogEntry, ReusableSpoolCatalogueSuggestion


class ReusableSpoolSuggestionsTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin = get_user_model().objects.create_superuser(username="spool-proposal-admin", email="admin@example.com", password="test")
        cls.user = get_user_model().objects.create_user(username="spool-proposal-user", password="test")

    def _post(self, path, value):
        return self.client.post(path, json.dumps(value), content_type="application/json")

    def test_suggestion_requires_permission_and_does_not_publish(self):
        self.client.force_login(self.user)
        data = {"manufacturer": "Example Maker", "name": "Sample Empty Master Spool",
                "design_type": "printed", "source_url": "https://example.org/masterspool",
                "proposed_specs": {"nominal_tare_g": "175.5"}}
        denied = self._post("/api/printing/reusable-spool-suggestions/", data)
        self.assertEqual(denied.status_code, 403)
        self.client.force_login(self.admin)
        response = self._post("/api/printing/reusable-spool-suggestions/", data)
        self.assertEqual(response.status_code, 201, response.content)
        self.assertFalse(ReusableSpoolCatalogEntry.objects.filter(manufacturer="Example Maker").exists())
        suggestion = ReusableSpoolCatalogueSuggestion.objects.get(pk=response.json()["id"])
        self.assertEqual(suggestion.status, "pending")

    def test_administrator_approval_creates_unverified_reference(self):
        self.client.force_login(self.admin)
        submitted = self._post("/api/printing/reusable-spool-suggestions/", {
            "manufacturer": "Example Maker", "name": "Empty Master Spool",
            "source_url": "https://example.org/product", "proposed_specs": {
                "nominal_tare_g": "183", "material": "PETG",
            },
        })
        self.assertEqual(submitted.status_code, 201, submitted.content)
        id_ = submitted.json()["id"]
        approved = self._post(f"/api/printing/reusable-spool-suggestions/{id_}/review/", {"action": "approve"})
        self.assertEqual(approved.status_code, 200, approved.content)
        entry = ReusableSpoolCatalogEntry.objects.get(manufacturer="Example Maker")
        self.assertFalse(entry.verified)
        self.assertEqual(str(entry.nominal_tare_g), "183.00")
        self.assertEqual(entry.provenance["source_type"], "user-suggested")
        second = self._post(f"/api/printing/reusable-spool-suggestions/{id_}/review/", {"action": "approve"})
        self.assertEqual(second.status_code, 404)

    def test_dryer_requires_evidence_and_bad_numbers_rejected(self):
        self.client.force_login(self.admin)
        for specs in ({"max_dryer_temp_c": 90}, {"nominal_tare_g": -1}, {"capacity_g": "nan"}):
            with self.subTest(specs=specs):
                result = self._post("/api/printing/reusable-spool-suggestions/", {
                    "manufacturer": "Example", "name": "Test",
                    "source_url": "https://example.org/item", "proposed_specs": specs,
                })
                self.assertEqual(result.status_code, 400, result.content)
        self.assertEqual(ReusableSpoolCatalogueSuggestion.objects.count(), 0)

    @patch("core.reusable_spool_discovery.fetch_catalogue_source_html")
    def test_source_preview_does_not_promote_html_or_claim_verified_specs(self, fetch):
        self.client.force_login(self.admin)
        fetch.return_value = ("https://example.org/products/reel", "<html><title>Master Spool Product</title></html>")
        response = self._post("/api/printing/reusable-spool-suggestions/preview/", {"url": "https://example.org/products/reel"})
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.json()["page_title"], "Master Spool Product")
        self.assertEqual(ReusableSpoolCatalogueSuggestion.objects.count(), 0)
