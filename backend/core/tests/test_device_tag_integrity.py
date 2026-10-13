"""Device tag write integrity: conflicts, rollback and ownership boundaries.

These are deterministic transaction tests; true parallel connection stress is
separate and should run against PostgreSQL rather than SQLite.
"""
import json
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.db import IntegrityError, transaction
from django.test import TestCase

from core.device_api_keys import generate_token
from core.models import FilamentProduct, InventoryItem, MakerTag, MakerTagEvent, Spool, UserApiKey


class DeviceTagIntegrityTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.owner = User.objects.create_user(username="tag-integrity", password="test")
        self.other = User.objects.create_user(username="tag-integrity-other", password="test")
        for code in ("add_makertag", "change_makertag", "view_spool", "view_inventoryitem"):
            self.owner.user_permissions.add(Permission.objects.get(content_type__app_label="core", codename=code))
        issued = generate_token()
        self.token = issued.plaintext
        UserApiKey.objects.create(owner=self.owner, name="RFID terminal", identifier=issued.identifier,
                                  secret_digest=issued.digest, scopes=["tags:write", "tags:read"])
        self.filament = FilamentProduct.objects.create(name="Tag Integrity PLA", material="PLA")
        self.spool1 = Spool.objects.create(owner=self.owner, spool_id="TI-1", filament=self.filament)
        self.spool2 = Spool.objects.create(owner=self.owner, spool_id="TI-2", filament=self.filament)
        self.other_spool = Spool.objects.create(owner=self.other, spool_id="TI-OTHER", filament=self.filament)

    def call(self, operation, uid="A1B2C3D4", target=None):
        return self.client.post(
            f"/api/device/v1/tags/{operation}/",
            data=json.dumps({"kind": "rfid", "uid": uid, "target_type": "spool",
                             "target_id": str(target or self.spool1.pk)}),
            content_type="application/json",
            HTTP_AUTHORIZATION="Bearer " + self.token,
        )

    def test_conflicting_registration_preserves_existing_target_and_mirror(self):
        first = self.call("register")
        self.assertEqual(first.status_code, 201, first.content)
        conflict = self.call("register", target=self.spool2.pk)
        self.assertEqual(conflict.status_code, 409, conflict.content)
        self.spool1.refresh_from_db()
        self.spool2.refresh_from_db()
        self.assertEqual(self.spool1.rfid_uid, "A1B2C3D4")
        self.assertEqual(self.spool2.rfid_uid, "")
        self.assertEqual(MakerTag.objects.count(), 1)
        self.assertEqual(MakerTagEvent.objects.count(), 1)

    def test_database_identity_unique_even_if_clients_race(self):
        self.assertEqual(self.call("register").status_code, 201)
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                MakerTag.objects.create(owner=self.other, kind="rfid", code="A1B2C3D4",
                                        target_type="spool", target_id=self.other_spool.pk)
        self.assertEqual(MakerTag.objects.count(), 1)

    def test_failed_reassignment_rolls_back_tag_and_spool_mirror(self):
        self.assertEqual(self.call("register").status_code, 201)
        # Simulate a failure after the tag row has been modified, but before
        # the legacy spool mirror can be changed.
        with patch("core.device_api_views._sync_rfid_tag_to_spool",
                   side_effect=__import__("django").core.exceptions.ValidationError("Simulated spool conflict")):
            result = self.call("assign", target=self.spool2.pk)
        self.assertEqual(result.status_code, 400, result.content)
        tag = MakerTag.objects.get()
        self.assertEqual(tag.target_id, self.spool1.pk)
        self.spool1.refresh_from_db()
        self.spool2.refresh_from_db()
        self.assertEqual(self.spool1.rfid_uid, "A1B2C3D4")
        self.assertEqual(self.spool2.rfid_uid, "")
        self.assertEqual(MakerTagEvent.objects.count(), 1)

    def test_failed_registration_rolls_back_tag_creation(self):
        from django.core.exceptions import ValidationError
        with patch("core.device_api_views._sync_rfid_tag_to_spool",
                   side_effect=ValidationError("Simulated mirror conflict")):
            result = self.call("register")
        self.assertEqual(result.status_code, 400, result.content)
        self.assertEqual(MakerTag.objects.count(), 0)
        self.assertEqual(MakerTagEvent.objects.count(), 0)
        self.spool1.refresh_from_db()
        self.assertEqual(self.spool1.rfid_uid, "")

    def test_foreign_spool_cannot_be_registered_or_assigned(self):
        self.assertEqual(self.call("register", target=self.other_spool.pk).status_code, 400)
        self.assertEqual(self.call("register").status_code, 201)
        self.assertEqual(self.call("assign", target=self.other_spool.pk).status_code, 400)
        self.assertEqual(MakerTag.objects.get().target_id, self.spool1.pk)
