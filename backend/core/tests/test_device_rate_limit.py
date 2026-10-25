"""Regression tests for shared device API throttles and retry semantics."""
import json
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.core.cache import cache
from django.test import TestCase, override_settings

from core.device_api_keys import generate_token
from core.models import InventoryItem, UserApiKey


@override_settings(CACHES={"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache", "LOCATION": "device-ratelimit-tests"}})
# These legacy behavioural tests use Django's non-TLS test client;
# production TLS enforcement is covered separately in test_device_api.py.
@override_settings(DEBUG=True)
class DeviceRateLimitTests(TestCase):
    def setUp(self):
        cache.clear()
        user = get_user_model().objects.create_user(username="rate-device", password="unused")
        for codename in ("add_makertag", "change_makertag", "view_inventoryitem"):
            user.user_permissions.add(Permission.objects.get(content_type__app_label="core", codename=codename))
        self.item = InventoryItem.objects.create(
            owner=user, inventory_id="OTH-7777", item_type="other",
            custom_name="Rate test", quantity=1,
        )
        issued = generate_token()
        self.token = issued.plaintext
        UserApiKey.objects.create(
            owner=user, name="Rate test", identifier=issued.identifier,
            secret_digest=issued.digest, scopes=["tags:read", "tags:write", "inventory:read"],
        )

    def headers(self, token=None):
        return {"HTTP_AUTHORIZATION": "Bearer " + (self.token if token is None else token)}

    @patch.dict("os.environ", {"MAKERVAULT_DEVICE_AUTH_FAILS_PER_MINUTE": "2"})
    def test_failed_auth_limit_does_not_count_success(self):
        for _ in range(5):
            self.assertEqual(self.client.get("/api/device/v1/me/", **self.headers()).status_code, 200)
        for _ in range(2):
            self.assertEqual(self.client.get("/api/device/v1/me/", **self.headers("invalid")).status_code, 401)
        denied = self.client.get("/api/device/v1/me/", **self.headers())
        self.assertEqual(denied.status_code, 429)
        self.assertIn("Retry-After", denied)
        self.assertEqual(denied["Cache-Control"], "no-store")

    @patch.dict("os.environ", {"MAKERVAULT_DEVICE_READS_PER_MINUTE": "2"})
    def test_read_limit_applies_across_endpoints(self):
        self.assertEqual(self.client.get("/api/device/v1/me/", **self.headers()).status_code, 200)
        self.assertEqual(self.client.get(
            "/api/device/v1/records/search/?type=inventory", **self.headers(),
        ).status_code, 200)
        self.assertEqual(self.client.get("/api/device/v1/me/", **self.headers()).status_code, 429)

    @patch.dict("os.environ", {"MAKERVAULT_DEVICE_WRITES_PER_MINUTE": "1"})
    def test_write_limit_does_not_create_second_tag(self):
        payload = {"kind": "nfc", "uid": "04010203040506", "target_type": "inventory", "target_id": str(self.item.pk)}
        endpoint = "/api/device/v1/tags/register/"
        first = self.client.post(endpoint, data=json.dumps(payload), content_type="application/json", **self.headers())
        self.assertEqual(first.status_code, 201, first.content)
        second = self.client.post(endpoint, data=json.dumps(payload), content_type="application/json", **self.headers())
        self.assertEqual(second.status_code, 429, second.content)

    @patch("core.device_rate_limit.cache.get", side_effect=ConnectionError("Redis unavailable"))
    def test_cache_outage_fails_closed(self, mocked):
        self.assertEqual(self.client.get("/api/device/v1/me/", **self.headers()).status_code, 503)
