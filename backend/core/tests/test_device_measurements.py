import json
from uuid import uuid4

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.test import TestCase

from core.device_api_keys import generate_token
from core.models import DeviceWeightMeasurement, Project, UserApiKey, FilamentProduct, Spool, ReusableSpoolDesign, ReusableSpool, MakerTag


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

    def test_spool_inventory_update_uses_linked_measured_tare(self):
        from decimal import Decimal
        filament = FilamentProduct.objects.create(name="PLA Weight Test", material="PLA")
        spool = Spool.objects.create(
            owner=self.owner, spool_id="SPL-WT-1", filament=filament,
            remaining_weight_g=Decimal("300.00"),
        )
        design = ReusableSpoolDesign.objects.create(owner=self.owner, name="Refill reel", nominal_tare_g=Decimal("175.00"))
        ReusableSpool.objects.create(
            owner=self.owner, design=design, code="REEL-WT-1",
            filament_spool=spool, measured_tare_g=Decimal("180.00"),
        )
        self.owner.user_permissions.add(Permission.objects.get(content_type__app_label="core", codename="change_spool"))
        data = self.payload(target_type="spool", target_id=str(spool.pk),
                            gross_weight_g="500.00", tare_weight_g="180.00",
                            update_inventory=True)
        preview = self.post("preview", data)
        self.assertEqual(preview.status_code, 200, preview.content)
        self.assertEqual(preview.json()["preview"]["known_tare"]["source"], "measured_reusable_spool")
        self.assertEqual(preview.json()["preview"]["known_tare"]["weight_g"], "180.00")
        confirmed = self.post("confirm", {**data, "preview_receipt": preview.json()["preview_receipt"]})
        self.assertEqual(confirmed.status_code, 201, confirmed.content)
        spool.refresh_from_db()
        self.assertEqual(spool.remaining_weight_g, Decimal("320.00"))
        record = DeviceWeightMeasurement.objects.get(request_id=data["request_id"])
        self.assertTrue(record.updated_spool)
        self.assertEqual(record.previous_spool_weight_g, Decimal("300.00"))

    def test_spool_known_tare_mismatch_cannot_update_inventory(self):
        from decimal import Decimal
        filament = FilamentProduct.objects.create(name="PETG Weight Test", material="PETG")
        spool = Spool.objects.create(owner=self.owner, spool_id="SPL-WT-2", filament=filament,
                                     remaining_weight_g=Decimal("400.00"))
        design = ReusableSpoolDesign.objects.create(owner=self.owner, name="Tare design",
                                                     nominal_tare_g=Decimal("170.00"))
        ReusableSpool.objects.create(owner=self.owner, design=design, code="REEL-WT-2", filament_spool=spool)
        self.owner.user_permissions.add(Permission.objects.get(content_type__app_label="core", codename="change_spool"))
        data = self.payload(target_type="spool", target_id=str(spool.pk),
                            gross_weight_g="520.00", tare_weight_g="160.00", update_inventory=True)
        self.assertEqual(self.post("confirm", data).status_code, 409)
        spool.refresh_from_db()
        self.assertEqual(spool.remaining_weight_g, Decimal("400.00"))
        self.assertFalse(DeviceWeightMeasurement.objects.filter(target_id=spool.pk).exists())

    def test_rfid_identifies_owned_spool_without_other_owner_leak(self):
        filament = FilamentProduct.objects.create(name="RFID Test", material="PLA")
        spool = Spool.objects.create(owner=self.owner, spool_id="SPL-WT-3", filament=filament,
                                     rfid_uid="A1B2C3D4")
        self.owner.user_permissions.add(Permission.objects.get(content_type__app_label="core", codename="view_spool"))
        path = "/api/device/v1/spools/identify/"
        result = self.client.post(path, data=json.dumps({"kind": "rfid", "uid": "A1:B2:C3:D4"}),
                                  content_type="application/json",
                                  HTTP_AUTHORIZATION="Bearer " + self.token)
        self.assertEqual(result.status_code, 200, result.content)
        self.assertEqual(result.json()["spool"]["id"], str(spool.pk))

    def test_stale_spool_preview_rejected_after_inventory_change(self):
        from decimal import Decimal
        filament = FilamentProduct.objects.create(name="Snapshot filament", material="PLA")
        spool = Spool.objects.create(owner=self.owner, spool_id="SP-SNAPSHOT", filament=filament,
                                     remaining_weight_g=Decimal("500.00"))
        self.owner.user_permissions.add(Permission.objects.get(content_type__app_label="core", codename="change_spool"))
        data = self.payload(target_type="spool", target_id=str(spool.pk),
                            gross_weight_g="550.00", tare_weight_g="150.00", update_inventory=True)
        preview = self.post("preview", data)
        self.assertEqual(preview.status_code, 200, preview.content)
        # Simulate another printer/device changing inventory before confirmation.
        spool.remaining_weight_g = Decimal("420.00")
        spool.save(update_fields=["remaining_weight_g", "updated_at"])
        rejected = self.post("confirm", {**data, "preview_receipt": preview.json()["preview_receipt"]})
        self.assertEqual(rejected.status_code, 409, rejected.content)
        spool.refresh_from_db()
        self.assertEqual(spool.remaining_weight_g, Decimal("420.00"))
        self.assertFalse(DeviceWeightMeasurement.objects.filter(target_id=spool.pk).exists())
        self.assertEqual(self.post("confirm", data).status_code, 201)

    def test_two_previews_for_same_spool_second_becomes_stale(self):
        from decimal import Decimal
        filament = FilamentProduct.objects.create(name="Concurrent filament", material="PETG")
        spool = Spool.objects.create(owner=self.owner, spool_id="SP-TWO", filament=filament,
                                     remaining_weight_g=Decimal("500.00"))
        self.owner.user_permissions.add(Permission.objects.get(content_type__app_label="core", codename="change_spool"))
        first = self.payload(target_type="spool", target_id=str(spool.pk),
                             gross_weight_g="540.00", tare_weight_g="140.00", update_inventory=True)
        second = self.payload(target_type="spool", target_id=str(spool.pk),
                              gross_weight_g="530.00", tare_weight_g="140.00", update_inventory=True)
        first_preview = self.post("preview", first).json()["preview_receipt"]
        second_preview = self.post("preview", second).json()["preview_receipt"]
        self.assertEqual(self.post("confirm", {**first, "preview_receipt": first_preview}).status_code, 201)
        rejected = self.post("confirm", {**second, "preview_receipt": second_preview})
        self.assertEqual(rejected.status_code, 409, rejected.content)
        spool.refresh_from_db()
        self.assertEqual(spool.remaining_weight_g, Decimal("400.00"))
        self.assertEqual(DeviceWeightMeasurement.objects.filter(target_id=spool.pk).count(), 1)
        # Retrying the first confirmation cannot write inventory a second time.
        retried = self.post("confirm", {**first, "preview_receipt": first_preview})
        self.assertEqual(retried.status_code, 200, retried.content)

    def test_preview_cannot_be_confirmed_with_different_device_key(self):
        data = self.payload()
        receipt = self.post("preview", data).json()["preview_receipt"]
        issued = generate_token()
        UserApiKey.objects.create(owner=self.owner, name="Other scale",
                                  identifier=issued.identifier, secret_digest=issued.digest,
                                  scopes=["spools:weight"])
        response = self.client.post("/api/device/v1/measurements/confirm/",
                                    data=json.dumps({**data, "preview_receipt": receipt}),
                                    content_type="application/json",
                                    HTTP_AUTHORIZATION="Bearer " + issued.plaintext)
        self.assertEqual(response.status_code, 409, response.content)
        self.assertEqual(DeviceWeightMeasurement.objects.count(), 0)
