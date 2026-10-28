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
        tag = MakerTag.objects.get(owner=self.owner, code="04AABBCCDDEEFF")
        from core.maker_tags import serialise_tag
        details = serialise_tag(tag)
        self.assertEqual(details["maker_tag_id"], "MV-" + tag.public_token.hex[:16].upper())
        self.assertEqual(details["code"], "04AABBCCDDEEFF")
        self.assertEqual(details["kind"], "nfc")
        self.assertEqual(MakerTag.objects.filter(owner=self.owner, code=tag.code).count(), 1)
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

    def test_nfc_and_rfid_kinds_share_one_physical_uid(self):
        # A UID registered through the legacy RFID option must not be
        # registered again as an NFC tag through the connected terminal.
        existing = MakerTag.objects.create(
            owner=self.owner, kind="rfid", code="04AABBCCDDEEFF",
            target_type="inventory", target_id=self.item.pk,
        )
        rid = self.start().json()["id"]
        response = self.complete(rid)
        self.assertEqual(response.status_code, 409)
        self.assertEqual(MakerTag.objects.filter(code=existing.code).count(), 1)

    def test_cross_kind_retry_is_idempotent(self):
        rid = self.start().json()["id"]
        self.assertEqual(self.complete(rid).status_code, 201)
        response = self.client.post(
            f"/api/device/v1/tag-registration/{rid}/complete/",
            data=json.dumps({"kind": "rfid", "uid": "04AABBCCDDEEFF"}),
            content_type="application/json",
            HTTP_AUTHORIZATION="Bearer " + self.token,
        )
        self.assertEqual(response.status_code, 200)

    def test_wrong_paired_terminal_cannot_poll_or_complete(self):
        rid = self.start().json()["id"]
        second_token = generate_token()
        other_key = UserApiKey.objects.create(
            owner=self.owner, name="Second terminal", identifier=second_token.identifier,
            secret_digest=second_token.digest, scopes=["tags:write"],
        )
        ConnectedDevice.objects.create(
            owner=self.owner, device_uid="second-rfid-terminal-149", name="Second terminal",
            device_type="rfid_terminal", api_key=other_key,
        )
        pending = self.client.get(
            "/api/device/v1/tag-registration/pending/",
            HTTP_AUTHORIZATION="Bearer " + second_token.plaintext,
        )
        self.assertEqual(pending.status_code, 200)
        self.assertIsNone(pending.json()["registration"])
        self.assertEqual(self.complete(rid, token=second_token.plaintext).status_code, 404)
        self.assertEqual(DeviceTagRegistration.objects.get(pk=rid).state, "pending")

    def test_revocation_blocks_pending_and_completion(self):
        rid = self.start().json()["id"]
        self.device.revoked_at = timezone.now()
        self.device.save(update_fields=["revoked_at"])
        response = self.client.get(
            "/api/device/v1/tag-registration/pending/",
            HTTP_AUTHORIZATION="Bearer " + self.token,
        )
        self.assertEqual(response.status_code, 403)
        self.assertEqual(self.complete(rid).status_code, 403)

    def test_browser_mutation_requires_csrf(self):
        from django.test import Client
        csrf_client = Client(enforce_csrf_checks=True)
        csrf_client.force_login(self.owner)
        response = csrf_client.post(
            "/api/device/tag-registration/",
            data=json.dumps({"device_id": str(self.device.pk), "target_type": "inventory",
                             "target_id": str(self.item.pk)}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 403)
        self.assertFalse(DeviceTagRegistration.objects.exists())

    @override_settings(DEBUG=False)
    def test_device_credentials_rejected_over_plain_http_in_production(self):
        response = self.client.get(
            "/api/device/v1/tag-registration/pending/",
            HTTP_AUTHORIZATION="Bearer " + self.token,
        )
        self.assertEqual(response.status_code, 403)

    def test_terminal_lookup_does_not_create_or_change_tag(self):
        known = MakerTag.objects.create(
            owner=self.owner, kind="nfc", code="04AABBCCDDEEFF",
            target_type="inventory", target_id=self.item.pk,
        )
        created = self.client.post(
            "/api/device/tag-lookup/",
            data=json.dumps({"device_id": str(self.device.pk)}),
            content_type="application/json",
        )
        self.assertEqual(created.status_code, 201, created.content)
        lookup_id = created.json()["id"]
        pending = self.client.get(
            "/api/device/v1/tag-lookup/pending/",
            HTTP_AUTHORIZATION="Bearer " + self.token,
        )
        self.assertEqual(pending.status_code, 200)
        self.assertEqual(pending.json()["lookup"]["id"], lookup_id)
        complete = self.client.post(
            f"/api/device/v1/tag-lookup/{lookup_id}/complete/",
            data=json.dumps({"kind": "rfid", "uid": "04AABBCCDDEEFF"}),
            content_type="application/json",
            HTTP_AUTHORIZATION="Bearer " + self.token,
        )
        self.assertEqual(complete.status_code, 201, complete.content)
        self.assertTrue(complete.json()["found"])
        self.assertEqual(complete.json()["tag"]["id"], str(known.pk))
        self.assertEqual(MakerTag.objects.count(), 1)
        self.assertEqual(self.client.get(f"/api/device/tag-lookup/{lookup_id}/").json()["state"], "completed")

    def test_terminal_lookup_unknown_uid_and_cancel(self):
        created = self.client.post(
            "/api/device/tag-lookup/",
            data=json.dumps({"device_id": str(self.device.pk)}),
            content_type="application/json",
        )
        self.assertEqual(created.status_code, 201, created.content)
        lookup_id = created.json()["id"]
        complete = self.client.post(
            f"/api/device/v1/tag-lookup/{lookup_id}/complete/",
            data=json.dumps({"kind": "nfc", "uid": "04AABBCCDDEEFF"}),
            content_type="application/json",
            HTTP_AUTHORIZATION="Bearer " + self.token,
        )
        self.assertEqual(complete.status_code, 201)
        self.assertFalse(complete.json()["found"])
        self.assertEqual(MakerTag.objects.count(), 0)
        other = self.client.post(
            "/api/device/tag-lookup/",
            data=json.dumps({"device_id": str(self.device.pk)}),
            content_type="application/json",
        )
        self.assertEqual(other.status_code, 201)
        second_id = other.json()["id"]
        self.assertEqual(self.client.post(f"/api/device/tag-lookup/{second_id}/cancel/").status_code, 200)
        rejected = self.client.post(
            f"/api/device/v1/tag-lookup/{second_id}/complete/",
            data=json.dumps({"kind": "nfc", "uid": "04AABBCCDDEEFF"}),
            content_type="application/json",
            HTTP_AUTHORIZATION="Bearer " + self.token,
        )
        self.assertEqual(rejected.status_code, 410)

