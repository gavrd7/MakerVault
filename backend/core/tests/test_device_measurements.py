import json
from uuid import uuid4

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.test import TestCase

from core.device_api_keys import generate_token
from core.models import DeviceWeightMeasurement, Project, UserApiKey


class DeviceMeasurementTests(TestCase):
    def setUp(self):
        self.owner = get_user_model().objects.create_user(username="weigh-owner", password="test")
        self.other = get_user_model().objects.create_user(username="weigh-other", password="test")
        self.project = Project.objects.create(owner=self.owner, name="Completed assembly")
        self.foreign = Project.objects.create(owner=self.other, name="Private assembly")
        self.owner.user_permissions.add(Permission.objects.get(content_type__app_label="core", codename="view_project"))
        issued = generate_token()
        self.token = issued.plaintext
        self.key = UserApiKey.objects.create(owner=self.owner, name="Scale", identifier=issued.identifier, secret_digest=issued.digest, scopes=["spools:weight"])

    def payload(self, **kwargs):
        data = {
            "request_id": str(uuid4()), "target_type": "project",
            "target_id": str(self.project.pk),
            "gross_weight_g": "152.25", "tare_weight_g": "2.25",
            "update_inventory": False,
        }
        data.update(kwargs)
        return data

    def post(self, endpoint, data):
        if endpoint == "confirm" and "preview_receipt" not in data:
            preview = self.post("preview", data)
            if preview.status_code == 200:
                data = {**data, "preview_receipt": preview.json()["preview_receipt"]}
        return self.client.post(
            "/api/device/v1/measurements/" + endpoint + "/",
            data=json.dumps(data), content_type="application/json",
            HTTP_AUTHORIZATION="Bearer " + self.token,
        )

    def test_preview_is_read_only_and_confirm_creates_one_history_row(self):
        data = self.payload()
        preview = self.post("preview", data)
        self.assertEqual(preview.status_code, 200, preview.content)
        self.assertEqual(preview.json()["preview"]["net_weight_g"], "150.00")
        self.assertEqual(DeviceWeightMeasurement.objects.count(), 0)
        confirmed = self.post("confirm", data)
        self.assertEqual(confirmed.status_code, 201, confirmed.content)
        self.assertEqual(self.post("confirm", data).status_code, 200)
        self.assertEqual(DeviceWeightMeasurement.objects.count(), 1)
        self.assertFalse(DeviceWeightMeasurement.objects.get().updated_spool)

    def test_replay_conflict_does_not_change_record(self):
        data = self.payload()
        self.assertEqual(self.post("confirm", data).status_code, 201)
        self.assertEqual(self.post("confirm", {**data, "gross_weight_g": "200.00"}).status_code, 409)
        self.assertEqual(DeviceWeightMeasurement.objects.count(), 1)

    def test_cross_owner_and_permissions(self):
        self.assertEqual(self.post("preview", self.payload(target_id=str(self.foreign.pk))).status_code, 404)
        self.owner.user_permissions.clear()
        self.assertEqual(self.post("confirm", self.payload()).status_code, 403)
        self.assertEqual(DeviceWeightMeasurement.objects.count(), 0)

    def test_rejects_invalid_readings_and_project_inventory_update(self):
        for changes in (
            {"gross_weight_g": "-1.00"},
            {"gross_weight_g": "NaN"},
            {"gross_weight_g": "1.00", "tare_weight_g": "2.00"},
            {"gross_weight_g": 40},
            {"gross_weight_g": "1.234"},
            {"update_inventory": True},
            {"target_type": "unknown"},
        ):
            with self.subTest(changes=changes):
                self.assertEqual(self.post("confirm", self.payload(**changes)).status_code, 400)
        self.assertEqual(DeviceWeightMeasurement.objects.count(), 0)

    def test_requires_scope_and_no_session_fallback(self):
        self.key.scopes = ["tags:read"]
        self.key.save(update_fields=["scopes"])
        self.assertEqual(self.post("preview", self.payload()).status_code, 403)
        self.client.force_login(self.owner)
        self.assertEqual(self.client.post("/api/device/v1/measurements/preview/", data="{}",
                                          content_type="application/json").status_code, 401)

    def test_confirmation_rejects_changed_payload_and_missing_preview(self):
        data = self.payload()
        receipt = self.post("preview", data).json()["preview_receipt"]
        changed = self.post("confirm", {**data, "gross_weight_g": "180.25", "preview_receipt": receipt})
        self.assertEqual(changed.status_code, 409, changed.content)
        self.assertEqual(DeviceWeightMeasurement.objects.count(), 0)
        missing = self.client.post(
            "/api/device/v1/measurements/confirm/", data=json.dumps(data),
            content_type="application/json", HTTP_AUTHORIZATION="Bearer " + self.token,
        )
        self.assertEqual(missing.status_code, 400)
        self.assertEqual(DeviceWeightMeasurement.objects.count(), 0)

    def test_history_uses_owner_and_model_permission(self):
        data = self.payload()
        self.assertEqual(self.post("confirm", data).status_code, 201)
        response = self.client.get(
            "/api/device/v1/measurements/history/?target_type=project&target_id=" + str(self.project.pk),
            HTTP_AUTHORIZATION="Bearer " + self.token,
        )
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(len(response.json()["rows"]), 1)
        denied = self.client.get(
            "/api/device/v1/measurements/history/?target_type=project&target_id=" + str(self.foreign.pk),
            HTTP_AUTHORIZATION="Bearer " + self.token,
        )
        self.assertEqual(denied.status_code, 404)

    def test_rfid_spool_identification_rejects_bad_uid_and_requires_permission(self):
        path = "/api/device/v1/spools/identify/"
        malformed = self.client.post(path, data=json.dumps({"kind": "rfid", "uid": "invalid"}),
                                     content_type="application/json",
                                     HTTP_AUTHORIZATION="Bearer " + self.token)
        self.assertEqual(malformed.status_code, 400)
        self.owner.user_permissions.add(
            Permission.objects.get(content_type__app_label="core", codename="view_spool")
        )
        unknown = self.client.post(path, data=json.dumps({"kind": "rfid", "uid": "A1B2C3D4"}),
                                   content_type="application/json",
                                   HTTP_AUTHORIZATION="Bearer " + self.token)
        self.assertEqual(unknown.status_code, 200, unknown.content)
        self.assertFalse(unknown.json()["found"])
