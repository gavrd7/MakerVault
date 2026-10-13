"""Software-only integration of independent RFID terminal and weigh station clients."""
import json
from unittest.mock import patch
from django.core import signing
from decimal import Decimal
from uuid import uuid4

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.test import Client, TestCase
from django.utils import timezone

from core.device_api_keys import generate_token
from core.models import (
    DeviceWeightMeasurement, FilamentProduct, MakerTag, MakerTagEvent,
    ReusableSpool, ReusableSpoolDesign, Spool, UserApiKey,
)


class SimulatedDeviceIntegrationTests(TestCase):
    def setUp(self):
        self.owner = get_user_model().objects.create_user(username="sim-device-owner", password="test")
        for codename in ("add_makertag", "change_makertag", "view_makertag", "view_spool", "change_spool"):
            self.owner.user_permissions.add(
                Permission.objects.get(content_type__app_label="core", codename=codename)
            )
        self.filament = FilamentProduct.objects.create(name="Simulated CFS PLA", material="PLA")
        self.spool = Spool.objects.create(
            owner=self.owner, spool_id="SIM-001", filament=self.filament,
            remaining_weight_g=Decimal("600.00"),
        )
        design = ReusableSpoolDesign.objects.create(
            owner=self.owner, name="Simulated refill reel", nominal_tare_g=Decimal("175.00")
        )
        ReusableSpool.objects.create(
            owner=self.owner, code="SIM-REEL", design=design,
            measured_tare_g=Decimal("180.00"), filament_spool=self.spool,
        )
        self.terminal_key, self.terminal_token = self.new_key("RFID terminal", ["tags:write", "tags:read"])
        self.scale_key, self.scale_token = self.new_key("Weigh station", ["spools:weight"])

    def new_key(self, name, scopes):
        issued = generate_token()
        return (UserApiKey.objects.create(
            owner=self.owner, name=name, identifier=issued.identifier,
            secret_digest=issued.digest, scopes=scopes,
        ), issued.plaintext)

    def post(self, path, payload, token):
        return Client().post(
            path, data=json.dumps(payload), content_type="application/json",
            HTTP_AUTHORIZATION="Bearer " + token,
        )

    def register(self):
        return self.post("/api/device/v1/tags/register/", {
            "kind": "rfid", "uid": "A1:B2:C3:D4",
            "target_type": "spool", "target_id": str(self.spool.pk),
        }, self.terminal_token)

    def reading(self, **changes):
        payload = {
            "request_id": str(uuid4()), "target_type": "spool",
            "target_id": str(self.spool.pk), "gross_weight_g": "650.00",
            "tare_weight_g": "180.00", "update_inventory": True,
        }
        payload.update(changes)
        return payload

    def preview(self, reading):
        return self.post("/api/device/v1/measurements/preview/", reading, self.scale_token)

    def confirm(self, reading):
        return self.post("/api/device/v1/measurements/confirm/", reading, self.scale_token)

    def test_complete_two_device_workflow_and_retry(self):
        registered = self.register()
        self.assertEqual(registered.status_code, 201, registered.content)
        self.spool.refresh_from_db()
        self.assertEqual(self.spool.rfid_uid, "A1B2C3D4")
        identified = self.post("/api/device/v1/spools/identify/", {
            "kind": "rfid", "uid": "A1B2C3D4",
        }, self.scale_token)
        self.assertEqual(identified.status_code, 200, identified.content)
        self.assertTrue(identified.json()["found"])
        found = identified.json()["spool"]
        self.assertEqual(found["id"], str(self.spool.pk))
        self.assertEqual(found["known_tare"]["weight_g"], "180.00")
        reading = self.reading()
        preview = self.preview(reading)
        self.assertEqual(preview.status_code, 200, preview.content)
        self.assertEqual(preview.json()["preview"]["net_weight_g"], "470.00")
        self.spool.refresh_from_db()
        self.assertEqual(self.spool.remaining_weight_g, Decimal("600.00"))
        reading["preview_receipt"] = preview.json()["preview_receipt"]
        first = self.confirm(reading)
        self.assertEqual(first.status_code, 201, first.content)
        retry = self.confirm(reading)  # Simulate lost response and exact retransmission.
        self.assertEqual(retry.status_code, 200, retry.content)
        self.assertFalse(retry.json()["created"])
        self.spool.refresh_from_db()
        self.assertEqual(self.spool.remaining_weight_g, Decimal("470.00"))
        self.assertEqual(DeviceWeightMeasurement.objects.count(), 1)
        record = DeviceWeightMeasurement.objects.get()
        self.assertEqual(record.previous_spool_weight_g, Decimal("600.00"))
        self.assertEqual(record.net_weight_g, Decimal("470.00"))
        history = Client().get(
            "/api/device/v1/measurements/history/",
            {"target_type": "spool", "target_id": str(self.spool.pk)},
            HTTP_AUTHORIZATION="Bearer " + self.scale_token,
        )
        self.assertEqual(history.status_code, 200, history.content)
        self.assertEqual(len(history.json()["rows"]), 1)
        resolved = self.post("/api/device/v1/tags/resolve/", {
            "kind": "rfid", "uid": "A1B2C3D4",
        }, self.terminal_token)
        self.assertEqual(resolved.status_code, 200, resolved.content)
        self.assertTrue(resolved.json()["found"])
        self.assertEqual(MakerTag.objects.count(), 1)
        self.assertEqual(MakerTagEvent.objects.count(), 1)

    def test_stale_measurement_requires_fresh_preview(self):
        self.assertEqual(self.register().status_code, 201)
        reading = self.reading()
        preview = self.preview(reading)
        self.assertEqual(preview.status_code, 200)
        self.spool.remaining_weight_g = Decimal("550.00")
        self.spool.save(update_fields=["remaining_weight_g", "updated_at"])
        old = self.confirm({**reading, "preview_receipt": preview.json()["preview_receipt"]})
        self.assertEqual(old.status_code, 409, old.content)
        self.assertEqual(DeviceWeightMeasurement.objects.count(), 0)
        next_preview = self.preview(reading)
        confirmed = self.confirm({**reading, "preview_receipt": next_preview.json()["preview_receipt"]})
        self.assertEqual(confirmed.status_code, 201, confirmed.content)
        self.spool.refresh_from_db()
        self.assertEqual(self.spool.remaining_weight_g, Decimal("470.00"))

    def test_revoke_terminal_does_not_disable_scale(self):
        self.terminal_key.revoked_at = timezone.now()
        self.terminal_key.save(update_fields=["revoked_at"])
        self.assertEqual(self.register().status_code, 401)
        unknown = self.post("/api/device/v1/spools/identify/", {
            "kind": "rfid", "uid": "A1B2C3D4",
        }, self.scale_token)
        self.assertEqual(unknown.status_code, 200)
        self.assertFalse(unknown.json()["found"])
        preview = self.preview(self.reading())
        self.assertEqual(preview.status_code, 200, preview.content)

    def test_scale_has_no_tag_write_scope(self):
        result = self.post("/api/device/v1/tags/register/", {
            "kind": "rfid", "uid": "A1B2C3D4",
            "target_type": "spool", "target_id": str(self.spool.pk),
        }, self.scale_token)
        self.assertEqual(result.status_code, 403)
        self.assertEqual(MakerTag.objects.count(), 0)

    def test_expired_preview_requires_new_preview_without_inventory_change(self):
        reading = self.reading()
        preview = self.preview(reading)
        self.assertEqual(preview.status_code, 200, preview.content)
        with patch("core.device_measurements.signing.loads",
                   side_effect=signing.SignatureExpired("Expired test receipt")):
            expired = self.confirm({**reading, "preview_receipt": preview.json()["preview_receipt"]})
        self.assertEqual(expired.status_code, 409, expired.content)
        self.spool.refresh_from_db()
        self.assertEqual(self.spool.remaining_weight_g, Decimal("600.00"))
        self.assertEqual(DeviceWeightMeasurement.objects.count(), 0)

    def test_lost_confirmation_response_can_retry_safely(self):
        reading = self.reading()
        receipt = self.preview(reading).json()["preview_receipt"]
        confirmed = {**reading, "preview_receipt": receipt}

        def transport_drops_response():
            # The API committed successfully, but its response never reached the device.
            response = self.confirm(confirmed)
            self.assertEqual(response.status_code, 201, response.content)
            raise TimeoutError("Simulated client connection loss after commit")

        with self.assertRaises(TimeoutError):
            transport_drops_response()
        retry = self.confirm(confirmed)
        self.assertEqual(retry.status_code, 200, retry.content)
        self.assertFalse(retry.json()["created"])
        self.spool.refresh_from_db()
        self.assertEqual(self.spool.remaining_weight_g, Decimal("470.00"))
        self.assertEqual(DeviceWeightMeasurement.objects.count(), 1)

    def test_rate_limited_confirm_then_retry(self):
        reading = self.reading()
        receipt = self.preview(reading).json()["preview_receipt"]
        confirmed = {**reading, "preview_receipt": receipt}
        with patch("core.device_api_views.device_request_allowed", return_value=(False, 17)):
            limited = self.confirm(confirmed)
        self.assertEqual(limited.status_code, 429, limited.content)
        self.assertEqual(limited["Retry-After"], "17")
        self.assertEqual(DeviceWeightMeasurement.objects.count(), 0)
        accepted = self.confirm(confirmed)
        self.assertEqual(accepted.status_code, 201, accepted.content)
        self.assertEqual(DeviceWeightMeasurement.objects.count(), 1)

    def test_temporary_throttling_service_outage_fails_closed_then_recovers(self):
        reading = self.reading()
        with patch("core.device_api_views.failed_auth_blocked", return_value=(None, 60)):
            unavailable = self.preview(reading)
        self.assertEqual(unavailable.status_code, 503, unavailable.content)
        self.assertEqual(DeviceWeightMeasurement.objects.count(), 0)
        healthy = self.preview(reading)
        self.assertEqual(healthy.status_code, 200, healthy.content)
