import json

from django.contrib.auth import get_user_model
from django.test import TestCase

from core.models import BoardModel, InventoryItem


class InventoryUnitCreationTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.user = User.objects.create_superuser(
            username="inventory-units-admin",
            email="inventory@example.test",
            password="test-password",
        )
        self.client.force_login(self.user)
        self.board = BoardModel.objects.create(name="Arduino Nano")

    def post_inventory(self, payload):
        return self.client.post(
            "/api/inventory/",
            data=json.dumps(payload),
            content_type="application/json",
        )

    def test_multiple_units_create_individual_inventory_records(self):
        response = self.post_inventory({
            "item_type": "board",
            "board_id": str(self.board.pk),
            "quantity": 4,
            "status": "available",
        })

        self.assertEqual(response.status_code, 201)
        payload = response.json()
        self.assertEqual(payload["created_count"], 4)
        self.assertEqual(len(payload["items"]), 4)
        self.assertEqual(len({item["inventory_id"] for item in payload["items"]}), 4)
        self.assertTrue(all(item["quantity"] == 1 for item in payload["items"]))
        self.assertEqual(
            InventoryItem.objects.filter(owner=self.user, board=self.board).count(),
            4,
        )

    def test_custom_inventory_id_requires_single_unit(self):
        response = self.post_inventory({
            "item_type": "board",
            "board_id": str(self.board.pk),
            "quantity": 2,
            "inventory_id": "MY-NANO",
        })

        self.assertEqual(response.status_code, 400)
        self.assertIn("inventory_id", response.json().get("fields", {}))
        self.assertFalse(InventoryItem.objects.filter(owner=self.user).exists())

    def test_existing_inventory_record_cannot_be_increased_above_one(self):
        item = InventoryItem.objects.create(
            owner=self.user,
            inventory_id="MCU-0001",
            item_type="board",
            board=self.board,
            quantity=1,
        )
        response = self.client.patch(
            f"/api/inventory/{item.pk}/",
            data=json.dumps({"quantity": 2}),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 400)
        item.refresh_from_db()
        self.assertEqual(item.quantity, 1)
