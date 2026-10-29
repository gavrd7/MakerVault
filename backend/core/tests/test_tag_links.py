"""Security and stable identity tests for phone-tappable Maker Tag links."""
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.test import TestCase

from core.models import InventoryItem, MakerTag


class MakerTagShortLinkTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.owner = User.objects.create_user(username="short-link-owner", password="test-password")
        self.other = User.objects.create_user(username="short-link-other", password="test-password")
        permissions = Permission.objects.filter(
            content_type__app_label="core",
            codename__in=["view_makertag", "view_inventoryitem"],
        )
        self.owner.user_permissions.add(*permissions)
        self.other.user_permissions.add(*permissions)
        self.item = InventoryItem.objects.create(
            owner=self.owner, inventory_id="OTH-4401", item_type="other",
            custom_name="NFC test item", quantity=1,
        )
        self.other_item = InventoryItem.objects.create(
            owner=self.other, inventory_id="OTH-4402", item_type="other",
            custom_name="Other NFC item", quantity=1,
        )
        self.tag = MakerTag.objects.create(
            owner=self.owner, kind="nfc", code="04AABBCCDD",
            target_type="inventory", target_id=self.item.pk,
        )

    def path(self, short_id=None):
        return f"/t/MV-{short_id or self.tag.short_id}/"

    def test_unauthenticated_requires_login(self):
        response = self.client.get(self.path())
        self.assertEqual(response.status_code, 302)
        self.assertIn("/accounts/login/", response["Location"])

    def test_owner_redirects_to_existing_app_scan(self):
        self.client.force_login(self.owner)
        response = self.client.get(self.path())
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response["Location"], f"/?tag={self.tag.public_token}")
        self.assertEqual(response["Cache-Control"], "no-store")

    def test_lowercase_identity_resolves(self):
        self.client.force_login(self.owner)
        response = self.client.get(self.path(self.tag.short_id.lower()).replace("/MV-", "/mv-"))
        self.assertEqual(response.status_code, 302)

    def test_other_owner_cannot_resolve(self):
        self.client.force_login(self.other)
        self.assertEqual(self.client.get(self.path()).status_code, 404)

    def test_retired_or_missing_target_not_resolved(self):
        self.client.force_login(self.owner)
        self.tag.status = "retired"
        self.tag.save(update_fields=["status"])
        self.assertEqual(self.client.get(self.path()).status_code, 404)
        self.tag.status = "active"
        self.tag.target_id = self.other_item.pk
        self.tag.save(update_fields=["status", "target_id"])
        self.assertEqual(self.client.get(self.path()).status_code, 404)

    def test_invalid_identity_and_methods(self):
        self.client.force_login(self.owner)
        self.assertEqual(self.client.get("/t/MV-BOGUS/").status_code, 404)
        self.assertEqual(self.client.post(self.path()).status_code, 405)

    def test_reassignment_preserves_short_link(self):
        self.client.force_login(self.owner)
        another = InventoryItem.objects.create(
            owner=self.owner, inventory_id="OTH-4403", item_type="other",
            custom_name="Replacement item", quantity=1,
        )
        before = self.client.get(self.path())
        self.tag.target_id = another.pk
        self.tag.save(update_fields=["target_id"])
        after = self.client.get(self.path())
        self.assertEqual(before["Location"], after["Location"])

    def test_without_view_permission_is_not_disclosed(self):
        self.client.force_login(self.owner)
        self.owner.user_permissions.clear()
        self.assertEqual(self.client.get(self.path()).status_code, 404)
