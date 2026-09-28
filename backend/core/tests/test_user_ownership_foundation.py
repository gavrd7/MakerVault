from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import TestCase

from core.models import (
    FileAsset,
    InventoryItem,
    Model3D,
    PrintJob,
    Printer,
    PrintingIntegrationSetting,
    PrintingLocation,
    Project,
    Spool,
    StorageSettings,
    UserStorageProfile,
)


class UserOwnershipFoundationTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_superuser(
            username="owner-a",
            email="owner-a@example.com",
            password="test-password",
        )
        self.client.force_login(self.user)

    def test_private_top_level_models_expose_owner_field(self):
        private_models = (
            Project,
            InventoryItem,
            FileAsset,
            PrintingLocation,
            PrintingIntegrationSetting,
            Spool,
            Printer,
            Model3D,
            PrintJob,
        )
        for model in private_models:
            with self.subTest(model=model.__name__):
                self.assertIsNotNone(model._meta.get_field("owner"))

    def test_project_creation_assigns_authenticated_owner(self):
        response = self.client.post(
            "/api/projects/",
            data={"name": "Private project", "status": "active"},
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 201, response.content)
        project = Project.objects.get(pk=response.json()["project"]["id"])
        self.assertEqual(project.owner, self.user)
        self.assertEqual(project.created_by, self.user)

    def test_inventory_creation_assigns_authenticated_owner(self):
        response = self.client.post(
            "/api/inventory/",
            data={
                "item_type": "other",
                "custom_name": "Private workshop item",
                "quantity": 1,
            },
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 201, response.content)
        item = InventoryItem.objects.get(pk=response.json()["item"]["id"])
        self.assertEqual(item.owner, self.user)

    def test_storage_defaults_and_override_validation(self):
        settings = StorageSettings.objects.create()
        self.assertEqual(settings.default_quota_bytes, 10 * 1024 * 1024 * 1024)

        profile = UserStorageProfile(user=self.user, quota_override_bytes=5 * 1024 * 1024 * 1024)
        profile.full_clean()
        profile.save()
        self.assertFalse(profile.quota_unlimited)

        profile.quota_override_bytes = -1
        with self.assertRaises(ValidationError):
            profile.full_clean()

    def test_personal_storage_endpoint_uses_instance_default_quota(self):
        response = self.client.get("/api/storage/")
        self.assertEqual(response.status_code, 200, response.content)
        payload = response.json()
        self.assertEqual(payload["used_bytes"], 0)
        self.assertEqual(payload["quota_bytes"], 10 * 1024 * 1024 * 1024)
        self.assertFalse(payload["unlimited"])
        self.assertEqual(
            payload["categories"],
            {"models": 0, "project_files": 0, "images": 0, "other_files": 0},
        )


class UserIsolationApiTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.alice = User.objects.create_superuser(
            username="alice", email="alice@example.com", password="test-password"
        )
        self.bob = User.objects.create_superuser(
            username="bob", email="bob@example.com", password="test-password"
        )
        self.alice_project = Project.objects.create(
            owner=self.alice, created_by=self.alice, name="Alice private project"
        )
        self.bob_project = Project.objects.create(
            owner=self.bob, created_by=self.bob, name="Bob private project"
        )
        self.alice_item = InventoryItem.objects.create(
            owner=self.alice,
            inventory_id="OTH-0001",
            item_type="other",
            custom_name="Alice item",
            quantity=1,
        )
        self.bob_item = InventoryItem.objects.create(
            owner=self.bob,
            inventory_id="OTH-0001",
            item_type="other",
            custom_name="Bob item",
            quantity=1,
        )
        self.client.force_login(self.alice)

    def test_lists_only_include_authenticated_users_private_records(self):
        projects = self.client.get("/api/projects/")
        self.assertEqual(projects.status_code, 200)
        project_ids = {row["id"] for row in projects.json()["rows"]}
        self.assertIn(str(self.alice_project.id), project_ids)
        self.assertNotIn(str(self.bob_project.id), project_ids)

        inventory = self.client.get("/api/inventory/")
        self.assertEqual(inventory.status_code, 200)
        item_ids = {row["id"] for row in inventory.json()["rows"]}
        self.assertIn(str(self.alice_item.id), item_ids)
        self.assertNotIn(str(self.bob_item.id), item_ids)

    def test_guessed_other_user_uuids_behave_as_not_found_even_for_staff(self):
        project = self.client.get(f"/api/projects/{self.bob_project.id}/")
        self.assertEqual(project.status_code, 404)

        item = self.client.get(f"/api/inventory/{self.bob_item.id}/")
        self.assertEqual(item.status_code, 404)

    def test_cross_owner_project_assignment_is_rejected_as_not_found(self):
        response = self.client.patch(
            f"/api/inventory/{self.alice_item.id}/",
            data={"project_id": str(self.bob_project.id)},
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 400)
        self.alice_item.refresh_from_db()
        self.assertIsNone(self.alice_item.project_id)

    def test_owner_scoped_identifiers_can_repeat_between_users(self):
        self.assertEqual(self.alice_item.inventory_id, self.bob_item.inventory_id)
        self.assertNotEqual(self.alice_item.owner_id, self.bob_item.owner_id)

    def test_model_validation_rejects_cross_owner_relationships(self):
        item = InventoryItem(
            owner=self.alice,
            inventory_id="OTH-0002",
            item_type="other",
            custom_name="Cross owner",
            quantity=1,
            project=self.bob_project,
        )
        with self.assertRaises(ValidationError):
            item.full_clean()

    def test_dashboard_counts_only_current_users_private_data(self):
        response = self.client.get("/api/dashboard/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["inventory_total"], 1)
        self.assertEqual(response.json()["projects_total"], 1)
