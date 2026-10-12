import json

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.test import TestCase
from django.utils import timezone

from core.device_api_keys import generate_token
from core.models import InventoryItem, MakerTag, UserApiKey


class DeviceApiTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.owner = User.objects.create_user(username="device-owner", password="password")
        self.other = User.objects.create_user(username="device-other", password="password")
        self.permission = Permission.objects.get(
            content_type__app_label="core", codename="view_makertag",
        )
        self.owner.user_permissions.add(self.permission)
        self.item = InventoryItem.objects.create(
            owner=self.owner, inventory_id="OTH-0401", item_type="other",
            custom_name="Tagged box", quantity=1,
        )
        self.tag = MakerTag.objects.create(
            owner=self.owner, kind="nfc", code="04AABBCCDDEEFF",
            target_type="inventory", target_id=self.item.pk, label="Box tag",
        )
        generated = generate_token()
        self.token = generated.plaintext
        self.key = UserApiKey.objects.create(
            owner=self.owner, name="RFID Reader", identifier=generated.identifier,
            secret_digest=generated.digest, scopes=["tags:read"],
        )

    def resolve(self, token=None, **fields):
        data = {"kind": "nfc", "uid": "04:aa:bb:cc:dd:ee:ff"}
        data.update(fields)
        headers = {"HTTP_AUTHORIZATION": "Bearer " + (token or self.token)}
        return self.client.post(
            "/api/device/v1/tags/resolve/", data=json.dumps(data),
            content_type="application/json", **headers,
        )

    def test_known_and_unknown_uid(self):
        result = self.resolve()
        self.assertEqual(result.status_code, 200, result.content)
        self.assertTrue(result.json()["found"])
        self.assertEqual(result.json()["tag"]["target"]["label"], "Tagged box")
        self.assertNotIn("metadata", result.json())
        other = self.resolve(uid="04AABBCCDDEE00")
        self.assertEqual(other.status_code, 200)
        self.assertFalse(other.json()["found"])

    def test_me_and_session_cookie_is_not_device_auth(self):
        result = self.client.get(
            "/api/device/v1/me/", HTTP_AUTHORIZATION="Bearer " + self.token,
        )
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.json()["capabilities"], ["tags:resolve"])
        self.client.force_login(self.owner)
        self.assertEqual(self.client.get("/api/device/v1/me/").status_code, 401)

    def test_revoke_expiry_scope_account_and_permissions(self):
        self.key.scopes = ["devices:status"]
        self.key.save(update_fields=["scopes"])
        self.assertEqual(self.resolve().status_code, 403)
        self.key.scopes = ["tags:read"]
        self.key.save(update_fields=["scopes"])
        self.owner.user_permissions.remove(self.permission)
        self.assertEqual(self.resolve().status_code, 403)
        self.owner.user_permissions.add(self.permission)
        self.key.expires_at = timezone.now() - timezone.timedelta(seconds=1)
        self.key.save(update_fields=["expires_at"])
        self.assertEqual(self.resolve().status_code, 401)
        self.key.expires_at = None
        self.key.revoked_at = timezone.now()
        self.key.save(update_fields=["expires_at", "revoked_at"])
        self.assertEqual(self.resolve().status_code, 401)
        self.key.revoked_at = None
        self.key.save(update_fields=["revoked_at"])
        self.owner.is_active = False
        self.owner.save(update_fields=["is_active"])
        self.assertEqual(self.resolve().status_code, 401)

    def test_invalid_payload_and_credentials(self):
        self.assertEqual(self.resolve(token="invalid").status_code, 401)
        for fields in ({"uid": "not-hex"}, {"kind": "qr"},
                       {"kind": []}, {"uid": "AA"}, {"uid": 123}):
            with self.subTest(fields=fields):
                self.assertEqual(self.resolve(**fields).status_code, 400)
        self.assertEqual(
            self.client.post("/api/device/v1/tags/resolve/", data="{" + "x" * 1050 + "}",
                             content_type="application/json",
                             HTTP_AUTHORIZATION="Bearer " + self.token).status_code,
            413,
        )

    def test_cross_owner_isolation_and_nonmatching_technology(self):
        self.assertFalse(self.resolve(kind="rfid").json()["found"])
        other_token = generate_token()
        UserApiKey.objects.create(
            owner=self.other, name="Other reader", identifier=other_token.identifier,
            secret_digest=other_token.digest, scopes=["tags:read"],
        )
        self.other.user_permissions.add(self.permission)
        self.assertFalse(self.resolve(token=other_token.plaintext).json()["found"])
