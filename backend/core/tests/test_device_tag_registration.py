"""Security and lifecycle tests for connected RFID terminal registration."""
import json
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.test import TestCase, override_settings
from django.utils import timezone

from core.device_api_keys import generate_token
from core.models import ConnectedDevice, DeviceTagRegistration, InventoryItem, MakerTag, UserApiKey


@override_settings(DEBUG=True)
class ConnectedTagRegistrationTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.owner = User.objects.create_user(username="tag-reg-owner", password="password")
        self.other = User.objects.create_user(username="tag-reg-other", password="password")
        for codename in ("add_makertag", "view_makertag", "view_inventoryitem"):
            perm = Permission.objects.get(content_type__app_label="core", codename=codename)
            self.owner.user_permissions.add(perm)
        self.item = InventoryItem.objects.create(
            owner=self.owner, inventory_id="OTH-1491", item_type="other",
            custom_name="Connected registration item", quantity=1,
        )
        token = generate_token()
        self.key = UserApiKey.objects.create(
            owner=self.owner, name="Handheld", identifier=token.identifier,
            secret_digest=token.digest, scopes=["tags:read", "tags:write", "devices:status"],
        )
        self.token = token.plaintext
        self.device = ConnectedDevice.objects.create(
            owner=self.owner, device_uid="test-rfid-terminal-149",
            name="Test terminal", device_type="rfid_terminal", api_key=self.key,
        )
        self.client.force_login(self.owner)

    def start(self, **overrides):
        payload = {"device_id": str(self.device.pk), "target_type": "inventory", "target_id": str(self.item.pk)}
        payload.update(overrides)
        return self.client.post(
            "/api/device/tag-registration/", data=json.dumps(payload), content_type="application/json"
        )

    def complete(self, session_id, *, uid="04AABBCCDDEEFF", token=None):
        return self.client.post(
            f"/api/device/v1/tag-registration/{session_id}/complete/",
            data=json.dumps({"kind": "nfc", "uid": uid}), content_type="application/json",
            HTTP_AUTHORIZATION="Bearer " + (token or self.token),
        )

    def test_create_poll_complete_and_retry(self):
        created = self.start()
        self.assertEqual(created.status_code, 201, created.content)
        rid = created.json()["id"]
        self.assertEqual(self.start().status_code, 409)
        pending = self.client.get("/api/device/v1/tag-registration/pending/", HTTP_AUTHORIZATION="Bearer " + self.token)
        self.assertEqual(pending.status_code, 200)
        self.assertEqual(pending.json()["registration"]["id"], rid)
        finished = self.complete(rid)
        self.assertEqual(finished.status_code, 201, finished.content)
        self.assertEqual(finished.json()["state"], "completed")
        self.assertEqual(self.complete(rid).status_code, 200)
        self.assertEqual(self.complete(rid, uid="04AABBCCDDEE00").status_code, 409)
        self.assertEqual(MakerTag.objects.filter(owner=self.owner, code="04AABBCCDDEEFF").count(), 1)
        self.assertEqual(self.client.get(f"/api/device/tag-registration/{rid}/").json()["state"], "completed")

    def test_cancel_and_expiry(self):
        rid = self.start().json()["id"]
        self.assertEqual(self.client.post(f"/api/device/tag-registration/{rid}/cancel/").status_code, 200)
        self.assertEqual(self.complete(rid).status_code, 410)
        second = self.start().json()["id"]
        DeviceTagRegistration.objects.filter(pk=second).update(expires_at=timezone.now() - timedelta(seconds=1))
        self.assertEqual(self.complete(second).status_code, 410)
        self.assertEqual(self.client.get(f"/api/device/tag-registration/{second}/").json()["state"], "expired")

    def test_other_owner_cannot_read_or_cancel(self):
        rid = self.start().json()["id"]
        self.client.force_login(self.other)
        self.assertEqual(self.client.get(f"/api/device/tag-registration/{rid}/").status_code, 404)
        self.assertEqual(self.client.post(f"/api/device/tag-registration/{rid}/cancel/").status_code, 404)
        self.assertEqual(self.start().status_code, 400)

    def test_unpaired_key_and_insufficient_scope(self):
        rid = self.start().json()["id"]
        rogue = generate_token()
        UserApiKey.objects.create(
            owner=self.owner, name="Not paired", identifier=rogue.identifier,
            secret_digest=rogue.digest, scopes=["tags:write"],
        )
        self.assertEqual(self.complete(rid, token=rogue.plaintext).status_code, 403)
        self.key.scopes = ["tags:read"]
        self.key.save(update_fields=["scopes"])
        self.assertEqual(self.complete(rid).status_code, 403)
        self.assertEqual(self.start().status_code, 403)

    def test_registered_tag_collision_is_not_reassigned(self):
        existing = MakerTag.objects.create(
            owner=self.owner, kind="nfc", code="04AABBCCDDEEFF",
            target_type="inventory", target_id=self.item.pk,
        )
        rid = self.start().json()["id"]
        self.assertEqual(self.complete(rid).status_code, 409)
        self.assertEqual(DeviceTagRegistration.objects.get(pk=rid).state, "pending")
        existing.refresh_from_db()
        self.assertEqual(existing.target_id, self.item.pk)
