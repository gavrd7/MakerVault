from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.test import TestCase

from core.models import (
    FilamentProduct,
    InventoryItem,
    MakerTag,
    Project,
    Spool,
)


class MakerTagApiTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.owner = User.objects.create_user(
            username="tag-owner",
            email="tag-owner@example.com",
            password="test-password",
        )
        self.other = User.objects.create_user(
            username="tag-other",
            email="tag-other@example.com",
            password="test-password",
        )
        permissions = Permission.objects.filter(
            content_type__app_label="core",
            codename__in=["add_makertag", "change_makertag"],
        )
        self.owner.user_permissions.add(*permissions)
        self.other.user_permissions.add(*permissions)

        self.inventory = InventoryItem.objects.create(
            owner=self.owner,
            inventory_id="OTH-0001",
            item_type="other",
            custom_name="Tagged storage box",
            quantity=1,
        )
        self.other_project = Project.objects.create(
            owner=self.other,
            created_by=self.other,
            name="Other user's project",
        )
        self.filament = FilamentProduct.objects.create(
            name="Maker Tag Test PLA",
            material="PLA",
        )
        self.spool = Spool.objects.create(
            owner=self.owner,
            spool_id="SPL-0001",
            filament=self.filament,
            rfid_uid="ABC123",
        )
        self.client.force_login(self.owner)

    def test_qr_tag_creation_generates_identity_and_history(self):
        response = self.client.post(
            "/api/tags/",
            data={
                "kind": "qr",
                "code": "",
                "label": "Storage box",
                "target_type": "inventory",
                "target_id": str(self.inventory.id),
            },
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 201, response.content)
        item = response.json()["item"]
        self.assertTrue(item["code"].startswith("MV-"))
        self.assertEqual(item["target"]["label"], "Tagged storage box")
        self.assertEqual(item["target_type"], "inventory")
        self.assertEqual(item["status"], "active")
        self.assertEqual(item["events"][0]["event_type"], "created")

    def test_tag_target_cannot_cross_owner_boundary(self):
        response = self.client.post(
            "/api/tags/",
            data={
                "kind": "qr",
                "target_type": "project",
                "target_id": str(self.other_project.id),
            },
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 400, response.content)
        self.assertEqual(MakerTag.objects.count(), 0)

    def test_tag_list_and_token_resolution_are_owner_scoped(self):
        owner_tag = MakerTag.objects.create(
            owner=self.owner,
            kind="qr",
            code="MV-OWNER",
            target_type="inventory",
            target_id=self.inventory.id,
        )
        other_tag = MakerTag.objects.create(
            owner=self.other,
            kind="qr",
            code="MV-OTHER",
            target_type="project",
            target_id=self.other_project.id,
        )

        response = self.client.get("/api/tags/")
        self.assertEqual(response.status_code, 200, response.content)
        ids = {row["id"] for row in response.json()["rows"]}
        self.assertEqual(ids, {str(owner_tag.id)})

        response = self.client.get(f"/api/tags/resolve/{other_tag.public_token}/")
        self.assertEqual(response.status_code, 404)

        response = self.client.get(f"/api/tags/resolve/{owner_tag.public_token}/")
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.json()["item"]["id"], str(owner_tag.id))

    def test_retired_tag_no_longer_resolves_but_keeps_history(self):
        tag = MakerTag.objects.create(
            owner=self.owner,
            kind="qr",
            code="MV-RETIRE",
            target_type="inventory",
            target_id=self.inventory.id,
        )
        response = self.client.patch(
            f"/api/tags/{tag.id}/",
            data={"status": "retired"},
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200, response.content)
        item = response.json()["item"]
        self.assertEqual(item["status"], "retired")
        self.assertIsNotNone(item["retired_at"])
        self.assertEqual(item["events"][0]["event_type"], "retired")

        response = self.client.get(f"/api/tags/resolve/{tag.public_token}/")
        self.assertEqual(response.status_code, 404)

    def test_rfid_tag_reuses_existing_spool_identity(self):
        response = self.client.post(
            "/api/tags/",
            data={
                "kind": "rfid",
                "code": "",
                "label": "Existing spool RFID",
                "target_type": "spool",
                "target_id": str(self.spool.id),
            },
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 201, response.content)
        self.assertEqual(response.json()["item"]["code"], "ABC123")
        self.spool.refresh_from_db()
        self.assertEqual(self.spool.rfid_uid, "ABC123")

    def test_new_rfid_tag_updates_spool_compatibility_field(self):
        self.spool.rfid_uid = ""
        self.spool.save(update_fields=["rfid_uid", "updated_at"])
        response = self.client.post(
            "/api/tags/",
            data={
                "kind": "rfid",
                "code": "04-aa-bb-cc",
                "target_type": "spool",
                "target_id": str(self.spool.id),
            },
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 201, response.content)
        self.spool.refresh_from_db()
        self.assertEqual(self.spool.rfid_uid, "04AABBCC")
        self.assertEqual(response.json()["item"]["code"], "04AABBCC")

    def test_reader_identity_preserves_case_when_not_a_hex_uid(self):
        response = self.client.post(
            "/api/tags/",
            data={
                "kind": "rfid",
                "code": "ReaderCode-AbC-42",
                "target_type": "inventory",
                "target_id": str(self.inventory.id),
                "metadata": {"technology": "usb_hid"},
            },
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 201, response.content)
        item = response.json()["item"]
        self.assertEqual(item["code"], "ReaderCode-AbC-42")
        self.assertEqual(item["technology"], "usb_hid")
        self.assertEqual(item["technology_label"], "USB / HID reader output")

    def test_opaque_spool_reader_identity_does_not_overwrite_legacy_rfid_uid(self):
        response = self.client.post(
            "/api/tags/",
            data={
                "kind": "rfid",
                "code": "PCReader-MixedCase-42",
                "target_type": "spool",
                "target_id": str(self.spool.id),
                "metadata": {"technology": "usb_hid"},
            },
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 201, response.content)
        self.spool.refresh_from_db()
        self.assertEqual(self.spool.rfid_uid, "ABC123")
        self.assertEqual(response.json()["item"]["code"], "PCReader-MixedCase-42")

    def test_auto_resolve_matches_reader_identity_without_knowing_tag_kind(self):
        tag = MakerTag.objects.create(
            owner=self.owner,
            kind="nfc",
            code="04:Aa:bb:CC",
            target_type="inventory",
            target_id=self.inventory.id,
            metadata={"technology": "iso14443"},
        )
        response = self.client.get("/api/tags/resolve/?kind=auto&code=04-aa-bb-cc")
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.json()["item"]["id"], str(tag.id))
        self.assertEqual(response.json()["item"]["code"], "04AABBCC")

    def test_tag_list_exposes_reader_technology_choices(self):
        response = self.client.get("/api/tags/")
        self.assertEqual(response.status_code, 200, response.content)
        values = {item["value"] for item in response.json()["technologies"]}
        self.assertTrue({"ndef", "iso14443", "iso15693", "lf_rfid", "uhf_epc", "usb_hid"} <= values)

    def test_physical_identity_cannot_be_duplicated_across_users(self):
        MakerTag.objects.create(
            owner=self.other,
            kind="nfc",
            code="04AABBCC",
            target_type="project",
            target_id=self.other_project.id,
        )
        response = self.client.post(
            "/api/tags/",
            data={
                "kind": "nfc",
                "code": "04AABBCC",
                "target_type": "inventory",
                "target_id": str(self.inventory.id),
            },
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 400, response.content)
