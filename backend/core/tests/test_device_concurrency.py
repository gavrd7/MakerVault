"""PostgreSQL-only concurrent requests through independent Django DB connections.

Runs with TransactionTestCase: unlike TestCase, test setup is committed and
worker threads can see it. No sleeps or assumptions about winning request.
"""
import json
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from threading import Barrier
from uuid import uuid4

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.db import connections
from django.test import Client, TransactionTestCase, override_settings

from core.device_api_keys import generate_token
from core.models import DeviceWeightMeasurement, FilamentProduct, MakerTag, MakerTagEvent, Spool, UserApiKey


# These legacy behavioural tests use Django's non-TLS test client;
# production TLS enforcement is covered separately in test_device_api.py.
@override_settings(DEBUG=True)
class PostgreSQLDeviceConcurrencyTests(TransactionTestCase):
    def setUp(self):
        if connections["default"].vendor != "postgresql":
            self.skipTest("Real concurrency validation requires PostgreSQL")
        self.owner = get_user_model().objects.create_user(username="concurrency-owner", password="test")
        for name in ("add_makertag", "change_makertag", "view_spool", "change_spool"):
            self.owner.user_permissions.add(Permission.objects.get(content_type__app_label="core", codename=name))
        self.filament = FilamentProduct.objects.create(name="Concurrency PLA", material="PLA")
        self.a = Spool.objects.create(owner=self.owner, spool_id="RACE-A", filament=self.filament,
                                      remaining_weight_g=Decimal("500.00"))
        self.b = Spool.objects.create(owner=self.owner, spool_id="RACE-B", filament=self.filament,
                                      remaining_weight_g=Decimal("500.00"))
        issued = generate_token()
        self.token = issued.plaintext
        UserApiKey.objects.create(owner=self.owner, name="Race device", identifier=issued.identifier,
                                  secret_digest=issued.digest, scopes=["tags:write", "spools:weight"])

    def post(self, path, payload):
        # Each worker has its own client and therefore its own DB connection.
        connections.close_all()
        try:
            return Client().post(path, data=json.dumps(payload), content_type="application/json",
                                 HTTP_AUTHORIZATION="Bearer " + self.token)
        finally:
            connections.close_all()

    def race(self, jobs):
        ready = Barrier(len(jobs))
        def run(job):
            ready.wait(timeout=15)
            return self.post(*job)
        with ThreadPoolExecutor(max_workers=len(jobs)) as pool:
            futures = [pool.submit(run, job) for job in jobs]
            return [future.result(timeout=25) for future in futures]

    def test_simultaneous_registration_same_uid_only_one_target(self):
        path = "/api/device/v1/tags/register/"
        def payload(target):
            return {"kind": "rfid", "uid": "A1B2C3D4",
                    "target_type": "spool", "target_id": str(target.pk)}
        responses = self.race([(path, payload(self.a)), (path, payload(self.b))])
        self.assertEqual(sorted(r.status_code for r in responses), [201, 409],
                         [r.content for r in responses])
        self.assertEqual(MakerTag.objects.filter(kind="rfid", code="A1B2C3D4").count(), 1)
        self.assertEqual(MakerTagEvent.objects.count(), 1)
        tag = MakerTag.objects.get(kind="rfid", code="A1B2C3D4")
        self.a.refresh_from_db()
        self.b.refresh_from_db()
        self.assertEqual(
            (self.a.rfid_uid, self.b.rfid_uid),
            ("A1B2C3D4", "") if tag.target_id == self.a.pk else ("", "A1B2C3D4"),
        )

    def test_simultaneous_spool_confirmations_only_one_updates(self):
        path = "/api/device/v1/measurements/"
        def payload(gross):
            return {"request_id": str(uuid4()), "target_type": "spool",
                    "target_id": str(self.a.pk), "gross_weight_g": gross,
                    "tare_weight_g": "150.00", "update_inventory": True}
        first, second = payload("540.00"), payload("530.00")
        for data in (first, second):
            response = self.post(path + "preview/", data)
            self.assertEqual(response.status_code, 200, response.content)
            data["preview_receipt"] = response.json()["preview_receipt"]
        responses = self.race([(path + "confirm/", first), (path + "confirm/", second)])
        self.assertEqual(sorted(r.status_code for r in responses), [201, 409],
                         [r.content for r in responses])
        self.a.refresh_from_db()
        record = DeviceWeightMeasurement.objects.get(target_id=self.a.pk)
        self.assertEqual(record.previous_spool_weight_g, Decimal("500.00"))
        self.assertEqual(self.a.remaining_weight_g, record.net_weight_g)
        self.assertEqual(DeviceWeightMeasurement.objects.filter(target_id=self.a.pk).count(), 1)
