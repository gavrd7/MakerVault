"""Read-only CFS tag UID matching must never disclose another user's spool."""
import json
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.test import RequestFactory, TestCase

from core.device_cfs_lookup import spool_by_rfid


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

    def test_permission_denial(self):
        status, _ = self.query({"uid": "04AABBCC"}, permission=False)
        self.assertEqual(status, 403)
