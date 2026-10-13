import json

from django.contrib.auth import get_user_model
from django.test import TestCase, Client
from django.utils import timezone

from core.device_api_keys import verify_token
from core.models import UserApiKey


class ApiKeyManagementTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.owner = User.objects.create_user(username="api-owner", password="owner-password")
        self.other = User.objects.create_user(username="api-other", password="other-password")
        self.client.force_login(self.owner)

    def issue(self, **overrides):
        payload = {"name": "Workshop terminal", "scopes": ["tags:read", "devices:status"], "expires_in_days": 90}
        payload.update(overrides)
        return self.client.post("/api/account/api-keys/", data=json.dumps(payload), content_type="application/json")

    def test_one_time_secret_is_hashed_and_not_listed(self):
        response = self.issue()
        self.assertEqual(response.status_code, 201, response.content)
        token = response.json()["token"]
        key = UserApiKey.objects.get(owner=self.owner)
        self.assertTrue(verify_token(token, key.secret_digest))
        self.assertNotEqual(key.secret_digest, token)
        self.assertNotIn(token, str(response.json()["item"]))
        listed = self.client.get("/api/account/api-keys/")
        self.assertEqual(listed.status_code, 200)
        self.assertEqual(len(listed.json()["rows"]), 1)
        self.assertNotIn(token, listed.content.decode())
        self.assertNotIn(key.secret_digest, listed.content.decode())
        self.assertEqual(key.scopes, ["devices:status", "tags:read"])
        self.assertIsNotNone(key.expires_at)

    def test_revoke_only_own_key_and_is_irreversible(self):
        response = self.issue()
        key_id = response.json()["item"]["id"]
        self.client.force_login(self.other)
        self.assertEqual(self.client.get("/api/account/api-keys/").json()["rows"], [])
        self.assertEqual(
            self.client.post(f"/api/account/api-keys/{key_id}/revoke/").status_code, 404
        )
        self.client.force_login(self.owner)
        self.assertEqual(
            self.client.post(f"/api/account/api-keys/{key_id}/revoke/").status_code, 200
        )
        self.assertFalse(UserApiKey.objects.get(id=key_id).is_active())
        self.assertEqual(
            self.client.post(f"/api/account/api-keys/{key_id}/revoke/").status_code, 200
        )
        self.assertIsNotNone(UserApiKey.objects.get(id=key_id).revoked_at)

    def test_invalid_scope_expiry_and_name_rejected(self):
        for payload in (
            {"scopes": ["admin:*"]}, {"scopes": []}, {"scopes": ["tags:read", "tags:read"]},
            {"expires_in_days": -1}, {"expires_in_days": True}, {"name": ""},
        ):
            with self.subTest(payload=payload):
                self.assertEqual(self.issue(**payload).status_code, 400)
        self.assertEqual(UserApiKey.objects.count(), 0)

    def test_authentication_and_csrf_required(self):
        self.client.logout()
        self.assertEqual(self.client.get("/api/account/api-keys/").status_code, 302)
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.owner)
        self.assertEqual(
            client.post("/api/account/api-keys/", data=json.dumps({
                "name": "should fail", "scopes": ["tags:read"]
            }), content_type="application/json").status_code,
            403,
        )
        self.assertEqual(UserApiKey.objects.count(), 0)

    def test_delete_requires_revocation_and_is_owner_scoped(self):
        response = self.issue()
        self.assertEqual(response.status_code, 201)
        key_id = response.json()["item"]["id"]
        endpoint = f"/api/account/api-keys/{key_id}/"

        # A live key must never be deleted without first being revoked.
        self.assertEqual(self.client.delete(endpoint).status_code, 409)
        self.assertTrue(UserApiKey.objects.filter(pk=key_id).exists())

        self.client.force_login(self.other)
        self.assertEqual(self.client.delete(endpoint).status_code, 404)
        self.client.force_login(self.owner)

        self.assertEqual(
            self.client.post(f"/api/account/api-keys/{key_id}/revoke/").status_code, 200
        )
        self.assertEqual(self.client.delete(endpoint).status_code, 200)
        self.assertFalse(UserApiKey.objects.filter(pk=key_id).exists())
        self.assertEqual(self.client.delete(endpoint).status_code, 404)

    def test_delete_requires_login_and_csrf(self):
        response = self.issue()
        key_id = response.json()["item"]["id"]
        self.client.post(f"/api/account/api-keys/{key_id}/revoke/")
        endpoint = f"/api/account/api-keys/{key_id}/"
        self.client.logout()
        self.assertEqual(self.client.delete(endpoint).status_code, 302)

        csrf_client = Client(enforce_csrf_checks=True)
        csrf_client.force_login(self.owner)
        self.assertEqual(csrf_client.delete(endpoint).status_code, 403)
        self.assertTrue(UserApiKey.objects.filter(pk=key_id).exists())


    def test_edit_scopes_does_not_rotate_secret_or_reveal_prefix(self):
        response = self.issue()
        secret = response.json()["token"]
        key_id = response.json()["item"]["id"]
        path = f"/api/account/api-keys/{key_id}/"
        changed = self.client.patch(
            path, data=json.dumps({"name": "Revised terminal", "scopes": ["tags:write"]}),
            content_type="application/json",
        )
        self.assertEqual(changed.status_code, 200, changed.content)
        key = UserApiKey.objects.get(pk=key_id)
        self.assertEqual(key.name, "Revised terminal")
        self.assertEqual(key.scopes, ["tags:write"])
        self.assertTrue(verify_token(secret, key.secret_digest))
        self.assertNotIn("token", changed.json())
        self.assertNotIn("prefix", changed.json()["item"])
        self.assertNotIn("prefix", self.client.get("/api/account/api-keys/").json()["rows"][0])

    def test_edit_scope_validation_owner_csrf_and_revocation(self):
        response = self.issue()
        key_id = response.json()["item"]["id"]
        path = f"/api/account/api-keys/{key_id}/"
        for payload in ({"scopes": []}, {"scopes": ["admin:*"]},
                        {"scopes": ["tags:read", "tags:read"]},
                        {"identifier": "bad"}, {"scopes": ["tags:read"], "revoked_at": None}):
            with self.subTest(payload=payload):
                result = self.client.patch(path, data=json.dumps(payload), content_type="application/json")
                self.assertEqual(result.status_code, 400, result.content)
        self.client.force_login(self.other)
        self.assertEqual(
            self.client.patch(path, data=json.dumps({"scopes": ["tags:read"]}), content_type="application/json").status_code, 404
        )
        self.client.force_login(self.owner)
        csrf_client = Client(enforce_csrf_checks=True)
        csrf_client.force_login(self.owner)
        self.assertEqual(
            csrf_client.patch(path, data=json.dumps({"scopes": ["tags:write"]}), content_type="application/json").status_code, 403
        )
        self.client.post(f"/api/account/api-keys/{key_id}/revoke/")
        self.assertEqual(
            self.client.patch(path, data=json.dumps({"scopes": ["tags:write"]}), content_type="application/json").status_code, 409
        )

    def test_key_expires_and_disabled_account_loses_validity(self):
        response = self.issue(expires_in_days=None)
        key = UserApiKey.objects.get(pk=response.json()["item"]["id"])
        self.assertTrue(key.is_active())
        key.expires_at = timezone.now() - timezone.timedelta(seconds=1)
        self.assertFalse(key.is_active())
        key.expires_at = None
        self.owner.is_active = False
        self.owner.save(update_fields=["is_active"])
        key.refresh_from_db()
        self.assertFalse(key.is_active())
