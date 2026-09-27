import hashlib
import shutil
import tempfile
from pathlib import Path

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings

from core.models import FileAsset, Project, RepositoryLink


class ProjectAssetApiTests(TestCase):
    def setUp(self):
        self.media_root = tempfile.mkdtemp(prefix="makervault-project-assets-")
        self.override = override_settings(MEDIA_ROOT=Path(self.media_root))
        self.override.enable()
        self.addCleanup(self.override.disable)
        self.addCleanup(shutil.rmtree, self.media_root, True)

        self.user = get_user_model().objects.create_superuser(
            username="asset-admin",
            email="asset@example.com",
            password="test-password",
        )
        self.client.force_login(self.user)
        self.project = Project.objects.create(name="Desk speaker", created_by=self.user)

    def test_project_file_upload_is_classified_hashed_and_returned_in_detail(self):
        payload = b"void setup() {}\nvoid loop() {}\n"
        response = self.client.post(
            f"/api/projects/{self.project.id}/files/",
            {
                "file": SimpleUploadedFile("speaker.ino", payload, content_type="text/plain"),
                "category": "source",
                "name": "Speaker firmware source",
                "version": "0.4.2",
                "description": "Arduino source for the speaker controller.",
            },
        )
        self.assertEqual(response.status_code, 201, response.content)

        asset = FileAsset.objects.get(project=self.project, category="source")
        self.assertEqual(asset.sha256, hashlib.sha256(payload).hexdigest())
        self.assertEqual(asset.version, "0.4.2")
        self.assertTrue(asset.file.storage.exists(asset.file.name))

        detail = self.client.get(f"/api/projects/{self.project.id}/")
        self.assertEqual(detail.status_code, 200)
        project = detail.json()["project"]
        self.assertEqual(project["file_count"], 1)
        self.assertEqual(project["files"][0]["name"], "Speaker firmware source")
        self.assertEqual(project["files"][0]["category_label"], "Source code")
        self.assertEqual(project["gallery"], [])

    def test_project_file_upload_rejects_image_category_and_unknown_extension(self):
        image_category = self.client.post(
            f"/api/projects/{self.project.id}/files/",
            {
                "file": SimpleUploadedFile("photo.jpg", b"not-an-image"),
                "category": "image",
            },
        )
        self.assertEqual(image_category.status_code, 400)

        unknown = self.client.post(
            f"/api/projects/{self.project.id}/files/",
            {
                "file": SimpleUploadedFile("payload.weird", b"unsupported"),
                "category": "other",
            },
        )
        self.assertEqual(unknown.status_code, 400)
        self.assertEqual(FileAsset.objects.filter(project=self.project).count(), 0)

    def test_deleting_project_file_removes_database_record_and_stored_file(self):
        upload = self.client.post(
            f"/api/projects/{self.project.id}/files/",
            {
                "file": SimpleUploadedFile("case.stl", b"solid case\nendsolid case\n"),
                "category": "mesh",
                "name": "Case",
            },
        )
        self.assertEqual(upload.status_code, 201, upload.content)
        asset = FileAsset.objects.get(project=self.project)
        stored_name = asset.file.name
        storage = asset.file.storage
        self.assertTrue(storage.exists(stored_name))

        response = self.client.delete(
            f"/api/projects/{self.project.id}/files/{asset.id}/"
        )
        self.assertEqual(response.status_code, 200)
        self.assertFalse(FileAsset.objects.filter(pk=asset.id).exists())
        self.assertFalse(storage.exists(stored_name))

    def test_global_file_library_returns_same_project_asset(self):
        upload = self.client.post(
            f"/api/projects/{self.project.id}/files/",
            {
                "file": SimpleUploadedFile("speaker.uf2", b"firmware-bytes"),
                "category": "firmware",
                "name": "Speaker firmware",
            },
        )
        self.assertEqual(upload.status_code, 201, upload.content)

        response = self.client.get("/api/files/")
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(len(payload["rows"]), 1)
        self.assertEqual(payload["rows"][0]["project"], "Desk speaker")
        self.assertEqual(payload["rows"][0]["category"], "firmware")
        self.assertTrue(any(item["value"] == "mesh" for item in payload["categories"]))

    def test_repository_link_is_returned_with_project(self):
        response = self.client.post(
            f"/api/projects/{self.project.id}/repositories/",
            data={
                "provider": "github",
                "name": "Desk speaker",
                "url": "https://github.com/example/desk-speaker",
                "default_branch": "main",
            },
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 201, response.content)
        self.assertEqual(RepositoryLink.objects.filter(project=self.project).count(), 1)

        detail = self.client.get(f"/api/projects/{self.project.id}/")
        project = detail.json()["project"]
        self.assertEqual(project["repository_count"], 1)
        self.assertEqual(project["repositories"][0]["provider_label"], "GitHub")
        self.assertEqual(project["repositories"][0]["default_branch"], "main")
