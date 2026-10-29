"""Security and lifecycle tests for paired terminal NDEF write requests."""
import json
from datetime import timedelta
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.test import TestCase, override_settings
from django.utils import timezone

from core.device_api_keys import generate_token
from core.models import ConnectedDevice, DeviceNdefWrite, InventoryItem, MakerTag, UserApiKey


@override_settings(DEBUG=True)
class DeviceNdefWriteTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.owner = User.objects.create_user(username="ndef-write-owner", password="password")
        self.other = User.objects.create_user(username="ndef-write-other", password="password")
        for codename in ("change_makertag", "view_makertag", "view_inventoryitem"):
            self.owner.user_permissions.add(Permission.objects.get(
                content_type__app_label="core", codename=codename))
        self.item = InventoryItem.objects.create(
            owner=self.owner, inventory_id="OTH-7007", item_type="other",
            custom_name="NDEF item", quantity=1,
        )
        self.tag = MakerTag.objects.create(
            owner=self.owner, kind="nfc", code="04AABBCCDDEEFF",
            target_type="inventory", target_id=self.item.pk,
        )
        token = generate_token()
        self.key = UserApiKey.objects.create(
            owner=self.owner, name="NDEF terminal", identifier=token.identifier,
            secret_digest=token.digest, scopes=["tags:read", "tags:write"],
        )
        self.token = token.plaintext
        self.device = ConnectedDevice.objects.create(
            owner=self.owner, device_uid="ndef-terminal-1", name="NDEF terminal",
            device_type="rfid_terminal", api_key=self.key,
            capabilities=["ntag215_ndef_write"],
        )
        self.client.force_login(self.owner)

    def start(self, **values):
        data = {"tag_id": str(self.tag.pk), "device_id": str(self.device.pk),
                "origin": "http://192.168.1.125:8000", "override": ""}
        data.update(values)
        return self.client.post("/api/device/ndef-write/", data=json.dumps(data),
                                content_type="application/json", HTTP_ORIGIN=data["origin"])

    def finish(self, pk, uid=None, url=None, token=None):
        item = DeviceNdefWrite.objects.get(pk=pk)
        body = {"uid": item.expected_uid if uid is None else uid,
                "verified_url": item.url if url is None else url}
        return self.client.post(f"/api/device/v1/ndef-write/{pk}/complete/",
                                data=json.dumps(body), content_type="application/json",
                                HTTP_AUTHORIZATION="Bearer " + (token or self.token))

    def test_create_poll_complete_and_idempotency(self):
        response = self.start()
        self.assertEqual(response.status_code, 201, response.content)
        payload = response.json()
        self.assertEqual(payload["maker_tag_id"], f"MV-{self.tag.short_id}")
        self.assertEqual(payload["url"], f"http://192.168.1.125:8000/t/MV-{self.tag.short_id}/")
        self.assertEqual(self.start().status_code, 409)
        pending = self.client.get("/api/device/v1/ndef-write/pending/",
                                  HTTP_AUTHORIZATION="Bearer " + self.token)
        self.assertEqual(pending.json()["request"]["id"], payload["id"])
        self.assertEqual(self.finish(payload["id"]).status_code, 200)
        self.assertEqual(self.finish(payload["id"]).json()["state"], "completed")
        self.assertEqual(self.finish(payload["id"], url="https://evil.test").status_code, 409)
        self.assertEqual(self.start().status_code, 201)

    def test_url_override_port_and_exact_verification(self):
        response = self.start(override="https://vault.example.com:8443")
        self.assertEqual(response.status_code, 201, response.content)
        pk = response.json()["id"]
        url = f"https://vault.example.com:8443/t/MV-{self.tag.short_id}/"
        self.assertEqual(response.json()["url"], url)
        self.assertEqual(self.finish(pk, url="https://vault.example.com/").status_code, 409)
        self.assertEqual(self.finish(pk, uid="04AABBCCDDEEEE").status_code, 409)
        self.assertEqual(self.finish(pk).json()["state"], "completed")

    def test_cancel_and_expiry(self):
        pk = self.start().json()["id"]
        self.assertEqual(self.client.post(f"/api/device/ndef-write/{pk}/cancel/").status_code, 200)
        self.assertEqual(self.finish(pk).status_code, 410)
        pk = self.start().json()["id"]
        DeviceNdefWrite.objects.filter(pk=pk).update(expires_at=timezone.now()-timedelta(seconds=1))
        self.assertEqual(self.finish(pk).status_code, 410)
        self.assertEqual(self.client.get(f"/api/device/ndef-write/{pk}/").json()["state"], "expired")

    def test_owner_and_capability_isolation(self):
        self.device.capabilities = []
        self.device.save(update_fields=["capabilities"])
        self.assertEqual(self.start().status_code, 403)
        self.device.capabilities = ["ntag215_ndef_write"]
        self.device.save(update_fields=["capabilities"])
        pk = self.start().json()["id"]
        self.client.force_login(self.other)
        self.assertEqual(self.client.get(f"/api/device/ndef-write/{pk}/").status_code, 404)
        self.assertEqual(self.client.post(f"/api/device/ndef-write/{pk}/cancel/").status_code, 404)
        self.client.force_login(self.owner)
        rogue = generate_token()
        UserApiKey.objects.create(owner=self.owner, name="Rogue", identifier=rogue.identifier,
                                  secret_digest=rogue.digest, scopes=["tags:write"])
        self.assertEqual(self.finish(pk, token=rogue.plaintext).status_code, 403)

    def test_no_unsafe_tag_or_browser_origin(self):
        self.assertEqual(self.start(origin="https://site.example/path").status_code, 400)
        self.assertEqual(self.start(override="javascript:alert(1)").status_code, 400)
        self.tag.status = "retired"
        self.tag.save(update_fields=["status"])
        self.assertEqual(self.start().status_code, 400)

    def test_device_cancel_is_bound_to_same_paired_terminal(self):
        pk = self.start().json()["id"]
        url = f"/api/device/v1/ndef-write/{pk}/cancel/"
        self.assertEqual(self.client.post(url).status_code, 401)
        rogue = generate_token()
        UserApiKey.objects.create(owner=self.owner, name="Other key",
                                  identifier=rogue.identifier,
                                  secret_digest=rogue.digest, scopes=["tags:write"])
        self.assertEqual(self.client.post(url, HTTP_AUTHORIZATION="Bearer " + rogue.plaintext).status_code, 403)
        self.assertEqual(self.client.post(url, HTTP_AUTHORIZATION="Bearer " + self.token).json()["state"], "cancelled")
        self.assertEqual(self.finish(pk).status_code, 410)

    def test_device_status_detects_cancel_and_changed_uid(self):
        pk = self.start().json()["id"]
        url = f"/api/device/v1/ndef-write/{pk}/status/"
        headers = {"HTTP_AUTHORIZATION": "Bearer " + self.token}
        self.assertEqual(self.client.get(url, **headers).json()["state"], "pending")
        self.tag.code = "04AABBCCDDFFEE"
        self.tag.save(update_fields=["code"])
        self.assertEqual(self.client.get(url, **headers).json()["state"], "invalid")
        self.assertEqual(self.client.post(f"/api/device/ndef-write/{pk}/cancel/").status_code, 200)
        self.assertEqual(self.client.get(url, **headers).json()["state"], "cancelled")
        self.assertEqual(self.client.get(url).status_code, 401)

    def test_reassignment_preserves_url_and_changed_uid_blocks_complete(self):
        pk = self.start().json()["id"]
        self.tag.code = "04AABBCCDDFFEE"
        self.tag.save(update_fields=["code"])
        self.assertEqual(self.finish(pk).status_code, 409)
        self.assertEqual(DeviceNdefWrite.objects.get(pk=pk).state, "pending")
