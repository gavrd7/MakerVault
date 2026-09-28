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
