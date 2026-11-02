"""Read-only CFS tag UID matching must never disclose another user's spool."""
import json
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import RequestFactory, TestCase, override_settings

from core.device_cfs_lookup import spool_by_rfid
from core.models import FilamentProduct, Spool, UserApiKey
from core.device_api_keys import generate_token
from django.contrib.auth.models import Permission


class ReadOnlyCfsLookupTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.owner = User.objects.create_user(username="cfs-reader-owner")
        self.other = User.objects.create_user(username="cfs-reader-other")
        self.factory = RequestFactory()

    def query(self, params, owner=None, permission=True):
        request = self.factory.get("/api/device/v1/spools/by-rfid/", params)
        request.device_owner = owner or self.owner
        view = spool_by_rfid.__wrapped__.__wrapped__.__wrapped__
        if permission:
            with patch.object(request.device_owner, "has_perm", return_value=True):
                result = view(request)
        else:
            result = view(request)
        return result.status_code, json.loads(result.content)

    def test_unassigned_uid_is_unmatched_without_changes(self):
        status, data = self.query({"uid": "04:AA:BB:CC"})
        self.assertEqual(status, 200)
        self.assertEqual(data, {"found": False, "uid": "04AABBCC", "status": "unmatched"})

    def test_invalid_uid_and_unexpected_fields_fail_closed(self):
        for params in (
            {"uid": "ZZZZZZZZ"},
            {"uid": "123"},
            {"uid": "0" * 22},
            {"uid": "04AABBCC", "material": "PLA"},
            {},
        ):
            with self.subTest(params=params):
                status, _ = self.query(params)
                self.assertEqual(status, 400)

    def test_owner_scoped_spool_match_without_mutation(self):
        product = FilamentProduct.objects.create(
            name="PLA Blue", material="PLA", color_name="Blue", color_hex="#3366CC"
        )
        own = Spool.objects.create(
            owner=self.owner, filament=product, spool_id="SPL-001",
            rfid_uid="04AABBCC", remaining_weight_g=450
        )
        other = Spool.objects.create(
            owner=self.other, filament=product, spool_id="SPL-SECRET",
            rfid_uid="11223344",
        )
        status, data = self.query({"uid": "04-aa-bb-cc"})
        self.assertEqual(status, 200)
        self.assertTrue(data["found"])
        self.assertEqual(data["spool"]["spool_id"], "SPL-001")
        self.assertEqual(data["spool"]["material"], "PLA")
        self.assertEqual(data["spool"]["remaining_weight_g"], "450.00")
        status, hidden = self.query({"uid": "11223344"})
        self.assertEqual(status, 200)
        self.assertFalse(hidden["found"])
        own.refresh_from_db()
        other.refresh_from_db()
        self.assertEqual(own.rfid_uid, "04AABBCC")
        self.assertEqual(other.rfid_uid, "11223344")

    def test_permission_denial(self):
        status, _ = self.query({"uid": "04AABBCC"}, permission=False)
        self.assertEqual(status, 403)


@override_settings(DEBUG=True)
class ReadOnlyCfsBearerTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.owner = User.objects.create_user(username="cfs-bearer-owner")
        self.owner.user_permissions.add(Permission.objects.get(
            content_type__app_label="core", codename="view_spool"
        ))
        generated = generate_token()
        self.token = generated.plaintext
        self.key = UserApiKey.objects.create(
            owner=self.owner, name="CFS terminal",
            identifier=generated.identifier, secret_digest=generated.digest,
            scopes=["inventory:read"],
        )

    def lookup(self, token=None):
        return self.client.get(
            "/api/device/v1/spools/by-rfid/?uid=04AABBCC",
            HTTP_AUTHORIZATION="Bearer " + (token or self.token),
        )

    def test_inventory_scope_required_and_session_cookie_is_not_a_bearer(self):
        self.assertEqual(self.lookup().status_code, 200)
        self.key.scopes = ["tags:read"]
        self.key.save(update_fields=["scopes"])
        self.assertEqual(self.lookup().status_code, 403)
        self.key.scopes = ["inventory:read"]
        self.key.save(update_fields=["scopes"])
        self.owner.user_permissions.clear()
        self.assertEqual(self.lookup().status_code, 403)
        self.client.force_login(self.owner)
        self.assertEqual(self.client.get("/api/device/v1/spools/by-rfid/?uid=04AABBCC").status_code, 401)


class CfsMaterialLookupTests(TestCase):
    def setUp(self):
        from core.models import Printer, PrinterConnection, PrinterMaterialDatabaseSnapshot
        from django.utils import timezone
        self.owner = get_user_model().objects.create_user(username="materials-owner")
        self.other = get_user_model().objects.create_user(username="materials-other")
        printer = Printer.objects.create(owner=self.owner, name="K2", model="K2")
        connection = PrinterConnection.objects.create(
            printer=printer, adapter="creality_local", enabled=True,
            endpoint_url="ws://192.0.2.10:9999"
        )
        PrinterMaterialDatabaseSnapshot.objects.create(
            connection=connection,
            payload={"result": {"list": [{"base": {
                "id": "07001", "brand": "Creality", "name": "CR-ABS",
            }}, {"base": {"id": "10437", "brand": "eSUN", "name": "PLA Basic"}}]}},
            synced_at=timezone.now(), byte_size=100,
        )
        self.factory = RequestFactory()

    def query(self, material_id, owner=None, extra=None, permitted=True):
        from core.device_cfs_lookup import material_by_id
        request = self.factory.get("/api/device/v1/cfs/material/",
                                   {"id": material_id, **(extra or {})})
        request.device_owner = owner or self.owner
        view = material_by_id.__wrapped__.__wrapped__.__wrapped__
        with patch.object(request.device_owner, "has_perm", return_value=permitted):
            response = view(request)
        return response.status_code, json.loads(response.content)

    def test_exact_material_code_and_leading_zero(self):
        status, result = self.query("07001")
        self.assertEqual(status, 200)
        self.assertTrue(result["found"])
        self.assertEqual(result["id"], "07001")
        self.assertEqual(result["name"], "CR-ABS")
        self.assertEqual(result["manufacturer"], "Creality")
        self.assertNotIn("spool", result)

    def test_unknown_code_and_owner_isolation(self):
        self.assertEqual(self.query("99999")[1]["status"], "unmatched")
        self.assertEqual(self.query("07001", owner=self.other)[1]["status"], "unmatched")

    def test_validation_and_permissions(self):
        for code in ("7001", "070001", "ABCDE", "../.."):
            self.assertEqual(self.query(code)[0], 400)
        self.assertEqual(self.query("07001", extra={"uid": "11223344"})[0], 400)
        self.assertEqual(self.query("07001", permitted=False)[0], 403)
