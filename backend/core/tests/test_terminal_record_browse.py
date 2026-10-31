"""Focused tests of the terminal paging view, independent of bearer middleware.

Bearer scope and TLS enforcement remain covered by the existing device API suite.
"""
import json

from django.contrib.auth import get_user_model
from django.test import RequestFactory, TestCase

from core.device_api_views import browse_records
from core.models import PrintingLocation


class TerminalRecordBrowseTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.owner = User.objects.create_superuser(
            username="browse-owner", email="browse-owner@example.test", password="unused-password"
        )
        self.other = User.objects.create_superuser(
            username="browse-other", email="browse-other@example.test", password="unused-password"
        )
        for name in ["Zebra", "Maple", "Apple", "Moon", "banana"]:
            PrintingLocation.objects.create(owner=self.owner, name=name)
        PrintingLocation.objects.create(owner=self.other, name="Private Location")
        self.factory = RequestFactory()

    def browse(self, params):
        req = self.factory.get("/api/device/v1/records/browse/", params)
        req.device_owner = self.owner
        # Unwrap GET and bearer decorators; test only the view's filtering/paging.
        view = browse_records.__wrapped__.__wrapped__
        response = view(req)
        return response.status_code, json.loads(response.content)

    def test_sorted_small_pages_and_owner_isolation(self):
        status, data = self.browse({"type": "location", "limit": "2"})
        self.assertEqual(status, 200)
        self.assertEqual([x["label"] for x in data["rows"]], ["Apple", "banana"])
        self.assertTrue(data["has_more"])
        self.assertEqual(data["next_offset"], 2)
        _, next_page = self.browse({"type": "location", "limit": "2", "offset": "2"})
        self.assertEqual([x["label"] for x in next_page["rows"]], ["Maple", "Moon"])
        _, last_page = self.browse({"type": "location", "limit": "2", "offset": "4"})
        self.assertEqual([x["label"] for x in last_page["rows"]], ["Zebra"])
        self.assertFalse(last_page["has_more"])

    def test_letter_jump_starts_at_or_after_letter(self):
        _, data = self.browse({"type": "location", "letter": "M", "limit": "10"})
        self.assertEqual([x["label"] for x in data["rows"]], ["Maple", "Moon", "Zebra"])
        _, data = self.browse({"type": "location", "letter": "Y"})
        self.assertEqual([x["label"] for x in data["rows"]], ["Zebra"])

    def test_invalid_parameters_and_empty_results(self):
        for params in [
            {"type": "location", "limit": "0"},
            {"type": "location", "limit": "21"},
            {"type": "location", "offset": "-1"},
            {"type": "location", "letter": "AA"},
            {"type": "unknown"},
        ]:
            status, _ = self.browse(params)
            self.assertEqual(status, 400, params)
        status, data = self.browse({"type": "location", "letter": "Z", "offset": "10"})
        self.assertEqual(status, 200)
        self.assertEqual(data["rows"], [])
