from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import TestCase
from django.core.files.uploadedfile import SimpleUploadedFile

from core.storage_usage import StorageQuotaExceeded, ensure_storage_capacity, storage_summary
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


    def test_quota_preflight_rejects_growth_beyond_effective_limit(self):
        profile, _ = UserStorageProfile.objects.get_or_create(user=self.user)
        profile.quota_override_bytes = 4
        profile.save(update_fields=["quota_override_bytes", "updated_at"])

        with self.assertRaises(StorageQuotaExceeded):
            ensure_storage_capacity(self.user, 5)

    def test_private_file_upload_is_blocked_before_storage_grows(self):
        profile, _ = UserStorageProfile.objects.get_or_create(user=self.user)
        profile.quota_override_bytes = 4
        profile.save(update_fields=["quota_override_bytes", "updated_at"])

        response = self.client.post(
            "/api/files/",
            data={
                "category": "other",
                "name": "Too large",
                "file": SimpleUploadedFile("quota-test.bin", b"12345"),
            },
        )
        self.assertEqual(response.status_code, 413, response.content)
        self.assertEqual(response.json()["code"], "storage_quota_exceeded")
        self.assertFalse(FileAsset.objects.filter(owner=self.user).exists())

    def test_storage_warning_levels_follow_80_90_100_thresholds(self):
        profile, _ = UserStorageProfile.objects.get_or_create(user=self.user)
        profile.quota_override_bytes = 100

        for used, expected in ((79, "ok"), (80, "warning"), (90, "critical"), (100, "full")):
            with self.subTest(used=used):
                profile.storage_used_bytes = used
                profile.save(update_fields=["quota_override_bytes", "storage_used_bytes", "updated_at"])
                self.assertEqual(storage_summary(self.user, refresh=False)["warning_level"], expected)


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


class AdministratorUserManagementTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.admin = User.objects.create_superuser(
            username="site-admin",
            email="site-admin@example.com",
            password="test-password",
        )
        self.member = User.objects.create_user(
            username="private-member",
            email="private-member@example.com",
            password="test-password",
        )
        self.project = Project.objects.create(
            owner=self.member,
            created_by=self.member,
            name="Secret member project",
        )
        self.inventory = InventoryItem.objects.create(
            owner=self.member,
            inventory_id="OTH-0001",
            item_type="other",
            custom_name="Secret member inventory",
            quantity=1,
        )
        self.asset = FileAsset.objects.create(
            owner=self.member,
            name="secret-design-file.3mf",
            category="slicer",
        )
        self.client.force_login(self.admin)

    def test_user_admin_list_returns_aggregates_without_private_content_names(self):
        response = self.client.get("/api/settings/users/")
        self.assertEqual(response.status_code, 200, response.content)
        member = next(row for row in response.json()["rows"] if row["username"] == self.member.username)
        self.assertEqual(member["counts"]["projects"], 1)
        self.assertEqual(member["counts"]["inventory"], 1)
        self.assertEqual(member["counts"]["files"], 1)
        body = response.content.decode("utf-8")
        self.assertNotIn("Secret member project", body)
        self.assertNotIn("Secret member inventory", body)
        self.assertNotIn("secret-design-file.3mf", body)

    def test_non_superuser_cannot_access_account_administration(self):
        self.client.force_login(self.member)
        response = self.client.get("/api/settings/users/")
        self.assertEqual(response.status_code, 403)

    def test_instance_storage_policy_supports_limited_and_unlimited(self):
        limited = self.client.patch(
            "/api/settings/storage-policy/",
            data={"mode": "limited", "default_quota_bytes": 123456},
            content_type="application/json",
        )
        self.assertEqual(limited.status_code, 200, limited.content)
        self.assertEqual(limited.json()["policy"]["default_quota_bytes"], 123456)
        self.assertEqual(limited.json()["policy"]["mode"], "limited")

        unlimited = self.client.patch(
            "/api/settings/storage-policy/",
            data={"mode": "unlimited"},
            content_type="application/json",
        )
        self.assertEqual(unlimited.status_code, 200, unlimited.content)
        self.assertEqual(unlimited.json()["policy"]["mode"], "unlimited")

        profile, _ = UserStorageProfile.objects.get_or_create(user=self.member)
        self.assertIsNone(storage_summary(self.member, refresh=False)["quota_bytes"])
        profile.quota_override_bytes = 2048
        profile.save(update_fields=["quota_override_bytes", "updated_at"])
        self.assertEqual(storage_summary(self.member, refresh=False)["quota_bytes"], 2048)

    def test_user_quota_can_use_default_override_or_unlimited(self):
        override = self.client.patch(
            f"/api/settings/users/{self.member.pk}/",
            data={"quota_mode": "override", "quota_bytes": 4096},
            content_type="application/json",
        )
        self.assertEqual(override.status_code, 200, override.content)
        self.assertEqual(override.json()["item"]["quota_mode"], "override")
        self.assertEqual(override.json()["item"]["storage"]["quota_bytes"], 4096)

        unlimited = self.client.patch(
            f"/api/settings/users/{self.member.pk}/",
            data={"quota_mode": "unlimited"},
            content_type="application/json",
        )
        self.assertEqual(unlimited.status_code, 200, unlimited.content)
        self.assertTrue(unlimited.json()["item"]["storage"]["unlimited"])

        default = self.client.patch(
            f"/api/settings/users/{self.member.pk}/",
            data={"quota_mode": "default"},
            content_type="application/json",
        )
        self.assertEqual(default.status_code, 200, default.content)
        self.assertEqual(default.json()["item"]["quota_mode"], "default")

    def test_account_can_be_disabled_and_reactivated_but_current_admin_cannot_disable_self(self):
        disabled = self.client.patch(
            f"/api/settings/users/{self.member.pk}/",
            data={"is_active": False},
            content_type="application/json",
        )
        self.assertEqual(disabled.status_code, 200, disabled.content)
        self.member.refresh_from_db()
        self.assertFalse(self.member.is_active)

        enabled = self.client.patch(
            f"/api/settings/users/{self.member.pk}/",
            data={"is_active": True},
            content_type="application/json",
        )
        self.assertEqual(enabled.status_code, 200, enabled.content)
        self.member.refresh_from_db()
        self.assertTrue(self.member.is_active)

        self_disable = self.client.patch(
            f"/api/settings/users/{self.admin.pk}/",
            data={"is_active": False},
            content_type="application/json",
        )
        self.assertEqual(self_disable.status_code, 400)
        self.admin.refresh_from_db()
        self.assertTrue(self.admin.is_active)

    def test_purge_requires_exact_username_and_preserves_account(self):
        rejected = self.client.post(
            f"/api/settings/users/{self.member.pk}/purge/",
            data={"confirm": "wrong"},
            content_type="application/json",
        )
        self.assertEqual(rejected.status_code, 400)
        self.assertTrue(Project.objects.filter(pk=self.project.pk).exists())

        purged = self.client.post(
            f"/api/settings/users/{self.member.pk}/purge/",
            data={"confirm": self.member.username},
            content_type="application/json",
        )
        self.assertEqual(purged.status_code, 200, purged.content)
        self.assertTrue(get_user_model().objects.filter(pk=self.member.pk).exists())
        self.assertFalse(Project.objects.filter(owner=self.member).exists())
        self.assertFalse(InventoryItem.objects.filter(owner=self.member).exists())
        self.assertFalse(FileAsset.objects.filter(owner=self.member).exists())
        self.assertEqual(purged.json()["item"]["storage"]["used_bytes"], 0)

    def test_delete_account_requires_confirmation_and_removes_private_data(self):
        rejected = self.client.delete(
            f"/api/settings/users/{self.member.pk}/delete/",
            data={"confirm": "wrong"},
            content_type="application/json",
        )
        self.assertEqual(rejected.status_code, 400)

        deleted = self.client.delete(
            f"/api/settings/users/{self.member.pk}/delete/",
            data={"confirm": self.member.username},
            content_type="application/json",
        )
        self.assertEqual(deleted.status_code, 200, deleted.content)
        self.assertFalse(get_user_model().objects.filter(pk=self.member.pk).exists())
        self.assertFalse(Project.objects.filter(owner_id=self.member.pk).exists())
