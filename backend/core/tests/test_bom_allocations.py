import importlib
import threading

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.management import call_command
from django.db import close_old_connections, connections, models
from django.test import Client, TestCase, TransactionTestCase

from core.models import BOMAllocation, BOMItem, InventoryHistory, InventoryItem, Project


class BomAllocationApiTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_superuser(
            username="bom-admin",
            email="bom@example.com",
            password="test-password",
        )
        self.client.force_login(self.user)
        self.project = Project.objects.create(owner=self.user, name="Voice speaker", created_by=self.user)
        self.other_project = Project.objects.create(owner=self.user, name="Other build", created_by=self.user)
        self.stock = InventoryItem.objects.create(owner=self.user, 
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

        second_stock = InventoryItem.objects.create(owner=self.user, 
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

    def test_inventory_detail_lists_active_bom_allocations_for_release_picker(self):
        bom = self.create_bom(quantity=2, name="M3 screws")
        allocation = self.allocate(bom["id"], 1.5).json()["allocation"]

        response = self.client.get(f"/api/inventory/{self.stock.id}/")
        self.assertEqual(response.status_code, 200)
        rows = response.json()["item"]["bom_allocations"]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["id"], allocation["id"])
        self.assertEqual(rows[0]["project_id"], str(self.project.id))
        self.assertEqual(rows[0]["project_name"], self.project.name)
        self.assertEqual(rows[0]["bom_item_id"], bom["id"])
        self.assertEqual(rows[0]["bom_item_name"], "M3 screws")
        self.assertEqual(rows[0]["quantity"], 1.5)
        self.assertEqual(rows[0]["unit"], "item")

    def test_inventory_quantity_cannot_drop_below_allocated_stock(self):
        bom = self.create_bom(quantity=3)
        self.assertEqual(self.allocate(bom["id"], 2).status_code, 201)

        response = self.client.patch(
            f"/api/inventory/{self.stock.id}/",
            data={"quantity": 1},
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("quantity", response.json().get("fields", {}))
        self.stock.refresh_from_db()
        self.assertEqual(float(self.stock.quantity), 5.0)

    def test_allocated_inventory_cannot_move_to_conflicting_project(self):
        bom = self.create_bom(quantity=1)
        self.assertEqual(self.allocate(bom["id"], 1).status_code, 201)

        response = self.client.patch(
            f"/api/inventory/{self.stock.id}/",
            data={"project_id": str(self.other_project.id)},
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("project_id", response.json().get("fields", {}))
        self.stock.refresh_from_db()
        self.assertIsNone(self.stock.project_id)

    def test_allocated_inventory_cannot_be_marked_repair_or_retired(self):
        bom = self.create_bom(quantity=1)
        self.assertEqual(self.allocate(bom["id"], 1).status_code, 201)

        for status in ("repair", "retired"):
            response = self.client.patch(
                f"/api/inventory/{self.stock.id}/",
                data={"status": status},
                content_type="application/json",
            )
            self.assertEqual(response.status_code, 400)
            self.assertIn("status", response.json().get("fields", {}))

        self.stock.refresh_from_db()
        self.assertEqual(self.stock.status, "available")

    def test_legacy_migration_caps_multiple_links_by_remaining_stock(self):
        migration = importlib.import_module("core.migrations.0005_bom_allocations")
        self.assertEqual(migration._legacy_allocation_quantity(4, 5, 0), 4)
        self.assertEqual(migration._legacy_allocation_quantity(4, 5, 4), 1)
        self.assertEqual(migration._legacy_allocation_quantity(2, 5, 5), 0)


    def test_create_inventory_and_allocate_from_bom_is_atomic(self):
        bom = self.create_bom(quantity=8, name="M3 screws")
        response = self.client.post(
            f"/api/projects/{self.project.id}/bom/{bom['id']}/allocations/",
            data={
                "quantity": 8,
                "notes": "First build allocation",
                "create_inventory": {
                    "quantity": 100,
                    "location": "Fasteners drawer",
                    "supplier": "Example supplier",
                    "purchase_price": "4.50",
                    "currency": "GBP",
                },
            },
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 201, response.content)
        payload = response.json()
        self.assertTrue(payload["created_inventory"])

        created = InventoryItem.objects.get(pk=payload["inventory_item"]["id"])
        self.assertEqual(created.item_type, "other")
        self.assertEqual(created.custom_name, "M3 screws")
        self.assertEqual(float(created.quantity), 100.0)
        self.assertIsNone(created.project_id)
        self.assertEqual(created.location, "Fasteners drawer")

        allocation = BOMAllocation.objects.get(
            bom_item_id=bom["id"],
            inventory_item=created,
        )
        self.assertEqual(float(allocation.quantity), 8.0)
        self.assertTrue(
            InventoryHistory.objects.filter(
                inventory_item=created,
                event_type="created",
            ).exists()
        )
        self.assertTrue(
            InventoryHistory.objects.filter(
                inventory_item=created,
                event_type="bom_allocated",
                project=self.project,
            ).exists()
        )

    def test_create_inventory_and_allocate_rolls_back_if_stock_is_too_small(self):
        bom = self.create_bom(quantity=8, name="M3 screws")
        before = InventoryItem.objects.count()
        response = self.client.post(
            f"/api/projects/{self.project.id}/bom/{bom['id']}/allocations/",
            data={
                "quantity": 8,
                "create_inventory": {
                    "quantity": 4,
                    "location": "Fasteners drawer",
                },
            },
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(InventoryItem.objects.count(), before)
        self.assertFalse(BOMAllocation.objects.filter(bom_item_id=bom["id"]).exists())

    def test_create_inventory_can_optionally_assign_whole_stock_to_project(self):
        bom = self.create_bom(quantity=1, name="Project-only part")
        response = self.client.post(
            f"/api/projects/{self.project.id}/bom/{bom['id']}/allocations/",
            data={
                "quantity": 1,
                "create_inventory": {
                    "quantity": 1,
                    "assign_to_project": True,
                },
            },
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 201, response.content)
        created = InventoryItem.objects.get(pk=response.json()["inventory_item"]["id"])
        self.assertEqual(created.project_id, self.project.id)

    def test_unallocated_inventory_can_be_deleted(self):
        disposable = InventoryItem.objects.create(owner=self.user, 
            inventory_id="OTH-MISTAKE",
            item_type="other",
            custom_name="Mistaken record",
            quantity=1,
            status="available",
        )
        response = self.client.delete(f"/api/inventory/{disposable.id}/")
        self.assertEqual(response.status_code, 200)
        self.assertFalse(InventoryItem.objects.filter(pk=disposable.id).exists())

    def test_editor_role_can_delete_inventory_but_does_not_gain_general_delete_rights(self):
        call_command("seed_roles")
        editor = get_user_model().objects.create_user(
            username="inventory-editor",
            email="inventory-editor@example.com",
            password="test-password",
        )
        editor.groups.add(Group.objects.get(name="Editor"))
        self.assertTrue(editor.has_perm("core.delete_inventoryitem"))
        self.assertFalse(editor.has_perm("core.delete_project"))

        disposable = InventoryItem.objects.create(
            owner=editor,
            inventory_id="OTH-EDITOR-MISTAKE",
            item_type="other",
            custom_name="Editor mistake",
            quantity=1,
            status="available",
        )
        self.client.force_login(editor)
        response = self.client.delete(f"/api/inventory/{disposable.id}/")
        self.assertEqual(response.status_code, 200)
        self.assertFalse(InventoryItem.objects.filter(pk=disposable.id).exists())


    def test_regular_user_cannot_mutate_project_bom(self):
        viewer = get_user_model().objects.create_user(
            username="viewer",
            email="viewer@example.com",
            password="viewer-password",
        )
        viewer_project = Project.objects.create(
            owner=viewer,
            created_by=viewer,
            name="Viewer-owned project",
        )
        self.client.force_login(viewer)
        response = self.client.post(
            f"/api/projects/{viewer_project.id}/bom/",
            data={"custom_name": "Denied", "quantity": 1, "unit": "item"},
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 403)
        self.assertEqual(BOMItem.objects.filter(project=viewer_project).count(), 0)



class BomAllocationConcurrencyTests(TransactionTestCase):
    reset_sequences = True

    def setUp(self):
        self.user = get_user_model().objects.create_superuser(
            username="bom-race-admin",
            email="bom-race@example.com",
            password="test-password",
        )
        self.project = Project.objects.create(owner=self.user, name="Concurrent build", created_by=self.user)
        self.stock = InventoryItem.objects.create(owner=self.user, 
            inventory_id="OTH-RACE",
            item_type="other",
            custom_name="Single stock item",
            quantity=1,
            status="available",
        )
        self.bom = BOMItem.objects.create(
            project=self.project,
            custom_name="Required item",
            quantity=1,
            unit="item",
        )

    def test_inventory_quantity_edit_and_allocation_cannot_race_past_stock_invariant(self):
        barrier = threading.Barrier(2)
        results = []
        errors = []

        def patch_quantity():
            close_old_connections()
            try:
                client = Client()
                client.force_login(self.user)
                barrier.wait()
                response = client.patch(
                    f"/api/inventory/{self.stock.id}/",
                    data={"quantity": 0},
                    content_type="application/json",
                )
                results.append(("patch", response.status_code))
            except Exception as exc:
                errors.append(exc)
            finally:
                connections.close_all()

        def allocate_stock():
            close_old_connections()
            try:
                client = Client()
                client.force_login(self.user)
                barrier.wait()
                response = client.post(
                    f"/api/projects/{self.project.id}/bom/{self.bom.id}/allocations/",
                    data={
                        "inventory_item_id": str(self.stock.id),
                        "quantity": 1,
                    },
                    content_type="application/json",
                )
                results.append(("allocate", response.status_code))
            except Exception as exc:
                errors.append(exc)
            finally:
                connections.close_all()

        first = threading.Thread(target=patch_quantity)
        second = threading.Thread(target=allocate_stock)
        first.start()
        second.start()
        first.join()
        second.join()

        self.assertEqual(errors, [])
        self.assertEqual(len(results), 2)
        statuses = sorted(status for _, status in results)
        self.assertEqual(statuses, [201, 400] if any(name == "allocate" and status == 201 for name, status in results) else [200, 400])

        self.stock.refresh_from_db()
        allocated = BOMAllocation.objects.filter(
            inventory_item=self.stock
        ).aggregate(total=models.Sum("quantity"))["total"] or 0
        self.assertLessEqual(allocated, self.stock.quantity)
