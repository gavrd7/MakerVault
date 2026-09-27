from django.contrib.auth import get_user_model
from django.test import TestCase

from core.models import BOMAllocation, BOMItem, InventoryHistory, InventoryItem, Project


class BomAllocationApiTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_superuser(
            username="bom-admin",
            email="bom@example.com",
            password="test-password",
        )
        self.client.force_login(self.user)
        self.project = Project.objects.create(name="Voice speaker", created_by=self.user)
        self.other_project = Project.objects.create(name="Other build", created_by=self.user)
        self.stock = InventoryItem.objects.create(
            inventory_id="OTH-0001",
            item_type="other",
            custom_name="M3 screws",
            quantity=5,
            status="available",
        )

    def create_bom(self, quantity=3, name="M3 screws"):
        response = self.client.post(
            f"/api/projects/{self.project.id}/bom/",
            data={
                "custom_name": name,
                "quantity": quantity,
                "unit": "item",
                "unit_cost": "0.10",
                "currency": "GBP",
            },
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 201, response.content)
        return response.json()["bom_item"]

    def allocate(self, bom_id, quantity, stock=None):
        stock = stock or self.stock
        return self.client.post(
            f"/api/projects/{self.project.id}/bom/{bom_id}/allocations/",
            data={
                "inventory_item_id": str(stock.id),
                "quantity": quantity,
            },
            content_type="application/json",
        )

    def test_bom_line_and_partial_allocation_are_serialised_with_coverage(self):
        bom = self.create_bom(quantity=3)
        response = self.allocate(bom["id"], 2)
        self.assertEqual(response.status_code, 201, response.content)

        detail = self.client.get(f"/api/projects/{self.project.id}/")
        self.assertEqual(detail.status_code, 200)
        project = detail.json()["project"]
        self.assertEqual(project["bom_summary"]["line_count"], 1)
        self.assertEqual(project["bom_summary"]["partial_lines"], 1)
        self.assertEqual(project["bom"][0]["allocated_quantity"], 2.0)
        self.assertEqual(project["bom"][0]["remaining_quantity"], 1.0)

        inventory = self.client.get("/api/inventory/").json()["rows"][0]
        self.assertEqual(inventory["quantity"], 5.0)
        self.assertEqual(inventory["allocated_quantity"], 2.0)
        self.assertEqual(inventory["available_quantity"], 3.0)

        self.assertTrue(
            InventoryHistory.objects.filter(
                inventory_item=self.stock,
                event_type="bom_allocated",
                project=self.project,
            ).exists()
        )

    def test_allocation_cannot_exceed_bom_remaining_quantity(self):
        bom = self.create_bom(quantity=2)
        first = self.allocate(bom["id"], 1.5)
        self.assertEqual(first.status_code, 201, first.content)

        second_stock = InventoryItem.objects.create(
            inventory_id="OTH-0002",
            item_type="other",
            custom_name="More screws",
            quantity=5,
            status="available",
        )
        response = self.allocate(bom["id"], 1, second_stock)
        self.assertEqual(response.status_code, 400)
        self.assertIn("quantity", response.json().get("fields", {}))
        self.assertEqual(BOMAllocation.objects.filter(bom_item_id=bom["id"]).count(), 1)

    def test_inventory_cannot_be_overallocated_across_bom_lines(self):
        first_bom = self.create_bom(quantity=4, name="Fasteners A")
        second_bom = self.create_bom(quantity=4, name="Fasteners B")
        first = self.allocate(first_bom["id"], 4)
        self.assertEqual(first.status_code, 201, first.content)

        response = self.allocate(second_bom["id"], 2)
        self.assertEqual(response.status_code, 400)
        self.assertIn("quantity", response.json().get("fields", {}))
        self.assertEqual(BOMAllocation.objects.filter(inventory_item=self.stock).count(), 1)

    def test_duplicate_inventory_allocation_on_same_bom_line_is_rejected(self):
        bom = self.create_bom(quantity=4)
        self.assertEqual(self.allocate(bom["id"], 1).status_code, 201)
        response = self.allocate(bom["id"], 1)
        self.assertEqual(response.status_code, 400)
        self.assertEqual(BOMAllocation.objects.filter(bom_item_id=bom["id"]).count(), 1)

    def test_stock_assigned_to_another_project_cannot_be_allocated(self):
        self.stock.project = self.other_project
        self.stock.save(update_fields=["project", "updated_at"])
        bom = self.create_bom(quantity=1)
        response = self.allocate(bom["id"], 1)
        self.assertEqual(response.status_code, 400)
        self.assertIn("inventory_item", response.json().get("fields", {}))

    def test_allocated_inventory_is_protected_from_deletion(self):
        bom = self.create_bom(quantity=1)
        self.assertEqual(self.allocate(bom["id"], 1).status_code, 201)

        response = self.client.delete(f"/api/inventory/{self.stock.id}/")
        self.assertEqual(response.status_code, 409)
        self.assertTrue(InventoryItem.objects.filter(pk=self.stock.id).exists())

    def test_bom_quantity_cannot_be_reduced_below_allocated_quantity(self):
        bom = self.create_bom(quantity=3)
        self.assertEqual(self.allocate(bom["id"], 2).status_code, 201)

        response = self.client.patch(
            f"/api/projects/{self.project.id}/bom/{bom['id']}/",
            data={"quantity": 1},
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("quantity", response.json().get("fields", {}))
        self.assertEqual(BOMItem.objects.get(pk=bom["id"]).quantity, 3)

    def test_releasing_allocation_restores_availability_and_records_history(self):
        bom = self.create_bom(quantity=2)
        allocation = self.allocate(bom["id"], 2).json()["allocation"]

        response = self.client.delete(
            f"/api/projects/{self.project.id}/bom/{bom['id']}/allocations/{allocation['id']}/"
        )
        self.assertEqual(response.status_code, 200)
        self.assertFalse(BOMAllocation.objects.filter(pk=allocation["id"]).exists())

        inventory = self.client.get("/api/inventory/").json()["rows"][0]
        self.assertEqual(inventory["allocated_quantity"], 0.0)
        self.assertEqual(inventory["available_quantity"], 5.0)
        self.assertTrue(
            InventoryHistory.objects.filter(
                inventory_item=self.stock,
                event_type="bom_released",
                project=self.project,
            ).exists()
        )

    def test_regular_user_cannot_mutate_project_bom(self):
        viewer = get_user_model().objects.create_user(
            username="viewer",
            email="viewer@example.com",
            password="viewer-password",
        )
        self.client.force_login(viewer)
        response = self.client.post(
            f"/api/projects/{self.project.id}/bom/",
            data={"custom_name": "Denied", "quantity": 1, "unit": "item"},
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 403)
        self.assertEqual(BOMItem.objects.filter(project=self.project).count(), 0)
