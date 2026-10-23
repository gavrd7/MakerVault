import json
import secrets

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings

from core.models import ConnectedDevice, DevicePairing, UserApiKey


@override_settings(DEBUG=True)
class PairingTests(TestCase):
    def setUp(self):
        self.owner = get_user_model().objects.create_user(username="pair-owner", password="testpass")
        self.other = get_user_model().objects.create_user(username="other-owner", password="testpass")
        self.proof = secrets.token_urlsafe(32)

    def post(self, path, body):
        return self.client.post(path, json.dumps(body), content_type="application/json")

    def start(self, uid="maker-terminal-001", kind="rfid_terminal"):
        return self.post("/api/device/v1/pairing/start/",
                         {"device_uid": uid, "device_type": kind, "claim_secret": self.proof})

    def approve(self, code, scopes=None):
        return self.post("/api/account/connected-devices/pair/approve/",
                         {"confirmation_code": code, "name": "Workbench Reader",
                          "scopes": scopes or ["tags:read"]})

    def complete(self, pairing_id, secret=None):
        return self.post(f"/api/device/v1/pairing/{pairing_id}/complete/",
                         {"claim_secret": self.proof if secret is None else secret})

    def test_owner_approves_and_device_claims_once(self):
        start = self.start()
        self.assertEqual(start.status_code, 201, start.content)
        claim = start.json()
        self.assertNotIn(self.proof, str(DevicePairing.objects.get(pk=claim["pairing_id"]).__dict__))
        self.assertEqual(self.complete(claim["pairing_id"]).status_code, 202)
        self.client.force_login(self.owner)
        self.assertEqual(self.approve(claim["confirmation_code"]).status_code, 200)
        self.client.logout()
        result = self.complete(claim["pairing_id"])
        self.assertEqual(result.status_code, 200, result.content)
        token = result.json()["api_key"]
        self.assertNotIn(token, str(UserApiKey.objects.first().__dict__))
        self.assertEqual(self.complete(claim["pairing_id"]).status_code, 410)
        self.assertEqual(self.client.get("/api/device/v1/me/", HTTP_AUTHORIZATION=f"Bearer {token}").status_code, 200)
        device = ConnectedDevice.objects.get()
        self.assertEqual(device.owner_id, self.owner.id)
        self.client.force_login(self.owner)
        self.assertEqual(self.post(f"/api/account/connected-devices/{device.pk}/revoke/", {}).status_code, 200)
        self.assertEqual(self.client.get("/api/device/v1/me/", HTTP_AUTHORIZATION=f"Bearer {token}").status_code, 401)

    def test_reject_wrong_proof_invalid_scopes_duplicate_and_expired(self):
        claim = self.start().json()
        self.client.force_login(self.owner)
        self.assertEqual(self.approve(claim["confirmation_code"], ["spools:weight"]).status_code, 400)
        self.assertEqual(self.approve(claim["confirmation_code"], ["tags:write"]).status_code, 200)
        self.assertEqual(self.approve(claim["confirmation_code"]).status_code, 409)
        self.client.logout()
        self.assertEqual(self.complete(claim["pairing_id"], "incorrect").status_code, 401)
        self.assertEqual(self.complete(claim["pairing_id"]).status_code, 200)
        self.assertEqual(self.start().status_code, 409)

        second = self.start(uid="maker-terminal-002").json()
        pairing = DevicePairing.objects.get(pk=second["pairing_id"])
        from django.utils import timezone
        pairing.expires_at = timezone.now() - timezone.timedelta(seconds=1)
        pairing.save(update_fields=["expires_at"])
        self.client.force_login(self.owner)
        self.assertEqual(self.approve(second["confirmation_code"]).status_code, 404)

    def test_cross_owner_isolation_and_session_not_device_auth(self):
        self.assertEqual(self.client.get("/api/account/connected-devices/").status_code, 302)
        self.client.force_login(self.owner)
        self.assertEqual(self.client.get("/api/device/v1/me/").status_code, 401)
        claim = self.start().json()
        self.assertEqual(self.approve(claim["confirmation_code"]).status_code, 200)
        self.client.logout()
        self.assertEqual(self.complete(claim["pairing_id"]).status_code, 200)
        device = ConnectedDevice.objects.get()
        self.client.force_login(self.other)
        self.assertEqual(self.client.get("/api/account/connected-devices/").json()["rows"], [])
        self.assertEqual(self.post(f"/api/account/connected-devices/{device.id}/revoke/", {}).status_code, 404)

    @override_settings(DEBUG=False)
    def test_tls_required_for_claims(self):
        self.assertEqual(self.start().status_code, 403)
