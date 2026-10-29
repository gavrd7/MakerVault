"""NDEF URL preview tests: origin fidelity, override, tenancy and bounds."""
import json

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.test import TestCase

from core.models import InventoryItem, MakerTag


class NdefPreviewTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.owner = User.objects.create_user(username="ndef-owner", password="test-password")
        self.other = User.objects.create_user(username="ndef-other", password="test-password")
        perm = Permission.objects.filter(content_type__app_label="core", codename__in=["change_makertag", "view_inventoryitem"])
        self.owner.user_permissions.add(*perm)
        self.item = InventoryItem.objects.create(
            owner=self.owner, inventory_id="OTH-5511", item_type="other",
            custom_name="Tag preview item", quantity=1
        )
        self.tag = MakerTag.objects.create(
            owner=self.owner, kind="nfc", code="04FACE1234",
            target_type="inventory", target_id=self.item.pk
        )
        self.url = f"/api/tags/{self.tag.pk}/ndef-preview/"
        self.client.force_login(self.owner)

    def preview(self, origin="http://192.168.1.125:8000", override="", header=None):
        return self.client.post(
            self.url, data=json.dumps({"origin": origin, "override": override}),
            content_type="application/json",
            HTTP_ORIGIN=origin if header is None else header,
        )

    def test_current_browser_origin_includes_port(self):
        result = self.preview()
        self.assertEqual(result.status_code, 200, result.content)
        data = result.json()
        self.assertEqual(data["url"], f"http://192.168.1.125:8000/t/MV-{self.tag.short_id}/")
        self.assertTrue(data["local_address_warning"])
        self.assertFalse(data["write_started"])

    def test_optional_https_override_includes_custom_port(self):
        data = self.preview(override="https://vault.example.com:8443").json()
        self.assertEqual(data["url"], f"https://vault.example.com:8443/t/MV-{self.tag.short_id}/")
        self.assertFalse(data["local_address_warning"])
        self.assertTrue(data["override"])

    def test_local_host_warning(self):
        self.assertTrue(self.preview(override="http://makervault.local:8000").json()["local_address_warning"])

    def test_mismatched_browser_origin_rejected(self):
        self.assertEqual(self.preview(header="https://other.example.com").status_code, 400)

    def test_malformed_and_unsafe_override_rejected(self):
        for value in (
            "javascript:alert(1)", "https://user:pass@host.example",
            "https://host.example/evil", "https://host.example?redirect=x",
            "https://host.example:99999", "http://bad host", "https://host.example#frag",
        ):
            with self.subTest(value=value):
                self.assertEqual(self.preview(override=value).status_code, 400)

    def test_nfc_only_and_active_only(self):
        self.tag.kind = "rfid"
        self.tag.save(update_fields=["kind"])
        self.assertEqual(self.preview().status_code, 404)
        self.tag.kind = "nfc"
        self.tag.status = "retired"
        self.tag.save(update_fields=["kind", "status"])
        self.assertEqual(self.preview().status_code, 404)

    def test_not_accessible_to_another_owner(self):
        self.client.force_login(self.other)
        self.assertEqual(self.preview().status_code, 403)
        self.other.user_permissions.add(Permission.objects.get(
            content_type__app_label="core", codename="change_makertag"))
        self.assertEqual(self.preview().status_code, 404)

    def test_no_write_or_tag_mutation(self):
        before = MakerTag.objects.get(pk=self.tag.pk)
        self.assertEqual(self.preview().status_code, 200)
        self.tag.refresh_from_db()
        self.assertEqual(self.tag.updated_at, before.updated_at)
        self.assertEqual(self.tag.code, before.code)
        self.assertEqual(self.tag.target_id, before.target_id)
