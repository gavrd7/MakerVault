import json

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.test import TestCase, override_settings

from core.device_api_keys import generate_token
from core.models import InventoryItem, MakerTag, MakerTagEvent, UserApiKey


# These legacy behavioural tests use Django's non-TLS test client;
# production TLS enforcement is covered separately in test_device_api.py.
@override_settings(DEBUG=True)
class DeviceTagWriteTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.owner = User.objects.create_user(username="device-writer", password="test")
        self.other = User.objects.create_user(username="device-stranger", password="test")
        self.a = InventoryItem.objects.create(owner=self.owner, inventory_id="OTH-8101", item_type="other", custom_name="Cabinet A", quantity=1)
        self.b = InventoryItem.objects.create(owner=self.owner, inventory_id="OTH-8102", item_type="other", custom_name="Cabinet B", quantity=1)
        self.foreign = InventoryItem.objects.create(owner=self.other, inventory_id="OTH-8103", item_type="other", custom_name="Private record", quantity=1)
        for code in ("add_makertag", "change_makertag", "view_inventoryitem"):
            self.owner.user_permissions.add(Permission.objects.get(content_type__app_label="core", codename=code))
        issued = generate_token()
        self.token = issued.plaintext
        self.key = UserApiKey.objects.create(owner=self.owner, name="Writer", identifier=issued.identifier, secret_digest=issued.digest, scopes=["tags:write", "inventory:read"])

    def call(self, path, data):
        return self.client.post(path, data=json.dumps(data), content_type="application/json", HTTP_AUTHORIZATION="Bearer " + self.token)

    def payload(self, **changes):
        data = {"kind": "nfc", "uid": "04:01:02:03:04:05:06", "target_type": "inventory", "target_id": str(self.a.pk)}
        data.update(changes)
        return data

    def test_register_idempotent_and_event_history(self):
        path = "/api/device/v1/tags/register/"
        first = self.call(path, self.payload())
        self.assertEqual(first.status_code, 201, first.content)
        self.assertTrue(first.json()["created"])
        repeat = self.call(path, self.payload())
        self.assertEqual(repeat.status_code, 200, repeat.content)
        self.assertFalse(repeat.json()["created"])
        self.assertEqual(MakerTag.objects.count(), 1)
        self.assertEqual(MakerTagEvent.objects.count(), 1)
        changed = self.call(path, self.payload(target_id=str(self.b.pk)))
        self.assertEqual(changed.status_code, 409)

    def test_assign_idempotent_and_history(self):
        self.call("/api/device/v1/tags/register/", self.payload())
        path = "/api/device/v1/tags/assign/"
        reassigned = self.call(path, self.payload(target_id=str(self.b.pk)))
        self.assertEqual(reassigned.status_code, 200, reassigned.content)
        self.assertTrue(reassigned.json()["changed"])
        self.assertEqual(MakerTagEvent.objects.count(), 2)
        again = self.call(path, self.payload(target_id=str(self.b.pk)))
        self.assertEqual(again.status_code, 200)
        self.assertFalse(again.json()["changed"])
        self.assertEqual(MakerTagEvent.objects.count(), 2)

    def test_cross_owner_and_scope_rejection(self):
        self.assertEqual(self.call("/api/device/v1/tags/register/", self.payload(target_id=str(self.foreign.pk))).status_code, 400)
        self.key.scopes = ["tags:read"]
        self.key.save(update_fields=["scopes"])
        self.assertEqual(self.call("/api/device/v1/tags/register/", self.payload()).status_code, 403)

    def test_record_search_only_owner_records(self):
        response = self.client.get("/api/device/v1/records/search/?type=inventory&q=Cabinet",
                                   HTTP_AUTHORIZATION="Bearer " + self.token)
        self.assertEqual(response.status_code, 200, response.content)
        names = [row["label"] for row in response.json()["rows"]]
        self.assertTrue(any("Cabinet A" in name for name in names))
        self.assertFalse(any("Private record" in name for name in names))

    def test_bad_tag_values_rejected(self):
        for value in ("invalid", "0102", "04__02", "Z" * 14):
            with self.subTest(value=value):
                result = self.call("/api/device/v1/tags/register/", self.payload(uid=value))
                self.assertEqual(result.status_code, 400, result.content)
        self.assertEqual(MakerTag.objects.count(), 0)

    def test_search_finds_records_beyond_first_500_candidates(self):
        # A record absent from the first 500 UUID-ordered candidates must
        # still be discoverable from an ESP32 terminal.
        from uuid import UUID
        InventoryItem.objects.bulk_create([
            InventoryItem(owner=self.owner, inventory_id=f"OTH-{n + 9000:05d}",
                          item_type="other", custom_name="Generic test part",
                          quantity=1, id=UUID(int=n + 1))
            for n in range(501)
        ])
        result = self.client.get(
            "/api/device/v1/records/search/?type=inventory&q=Cabinet&limit=25",
            HTTP_AUTHORIZATION="Bearer " + self.token,
        )
        self.assertEqual(result.status_code, 200, result.content)
        self.assertTrue(any("Cabinet" in row["label"] for row in result.json()["rows"]))

    def test_search_permission_revoked(self):
        permission = Permission.objects.get(content_type__app_label="core", codename="view_inventoryitem")
        self.owner.user_permissions.remove(permission)
        result = self.client.get(
            "/api/device/v1/records/search/?type=inventory",
            HTTP_AUTHORIZATION="Bearer " + self.token,
        )
        self.assertEqual(result.status_code, 403)

    def test_reassignment_cannot_cross_owner(self):
        self.assertEqual(self.call("/api/device/v1/tags/register/", self.payload()).status_code, 201)
        result = self.call("/api/device/v1/tags/assign/", self.payload(target_id=str(self.foreign.pk)))
        self.assertEqual(result.status_code, 400)
        tag = MakerTag.objects.get(owner=self.owner, kind="nfc")
        self.assertEqual(tag.target_id, self.a.pk)
        self.assertEqual(MakerTagEvent.objects.filter(tag=tag).count(), 1)

    def test_oversized_write_requests_return_413_without_changes(self):
        for endpoint in ("register", "assign"):
            with self.subTest(endpoint=endpoint):
                response = self.client.post(
                    f"/api/device/v1/tags/{endpoint}/",
                    data="{" + "x" * 1100 + "}",
                    content_type="application/json",
                    HTTP_AUTHORIZATION="Bearer " + self.token,
                )
                self.assertEqual(response.status_code, 413, response.content)
                self.assertEqual(response["Cache-Control"], "no-store")
        self.assertEqual(MakerTag.objects.count(), 0)

    def test_malformed_json_and_target_ids_rejected(self):
        for endpoint in ("register", "assign"):
            path = f"/api/device/v1/tags/{endpoint}/"
            with self.subTest(endpoint=endpoint):
                malformed = self.client.post(
                    path, data="{bad json",
                    content_type="application/json",
                    HTTP_AUTHORIZATION="Bearer " + self.token,
                )
                self.assertEqual(malformed.status_code, 400, malformed.content)
                invalid_id = self.call(path, self.payload(target_id="not-a-uuid"))
                self.assertEqual(invalid_id.status_code, 400, invalid_id.content)
        self.assertEqual(MakerTag.objects.count(), 0)

    def test_revoked_write_key_rejected(self):
        from django.utils import timezone
        self.key.revoked_at = timezone.now()
        self.key.save(update_fields=["revoked_at"])
        response = self.call("/api/device/v1/tags/register/", self.payload())
        self.assertEqual(response.status_code, 401)
        self.assertEqual(MakerTag.objects.count(), 0)

    def test_retired_and_foreign_tag_cannot_be_reassigned(self):
        self.call("/api/device/v1/tags/register/", self.payload())
        tag = MakerTag.objects.get(owner=self.owner)
        tag.status = "retired"
        tag.save(update_fields=["status"])
        self.assertEqual(
            self.call("/api/device/v1/tags/assign/", self.payload(target_id=str(self.b.pk))).status_code,
            404,
        )
        self.assertEqual(MakerTagEvent.objects.filter(tag=tag).count(), 1)
