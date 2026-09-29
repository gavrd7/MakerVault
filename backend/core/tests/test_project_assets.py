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
        self.project = Project.objects.create(owner=self.user, name="Desk speaker", created_by=self.user)

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

    def test_standalone_file_upload_uses_existing_file_type_validator(self):
        payload = b"print('standalone')\n"
        response = self.client.post(
            "/api/files/",
            {
                "file": SimpleUploadedFile("utility.py", payload, content_type="text/plain"),
                "category": "source",
                "name": "Standalone utility",
                "version": "1.0",
            },
        )
        self.assertEqual(response.status_code, 201, response.content)

        asset = FileAsset.objects.get(name="Standalone utility")
        self.assertIsNone(asset.project)
        self.assertEqual(asset.sha256, hashlib.sha256(payload).hexdigest())

        library = self.client.get("/api/files/?project=__standalone__")
        self.assertEqual(library.status_code, 200)
        self.assertEqual(len(library.json()["rows"]), 1)
        self.assertEqual(library.json()["rows"][0]["project_id"], "")

        rejected = self.client.post(
            "/api/files/",
            {
                "file": SimpleUploadedFile("unsupported.weird", b"not allowed"),
                "category": "other",
            },
        )
        self.assertEqual(rejected.status_code, 400)

    def test_standalone_file_can_be_attached_to_project_without_reupload(self):
        upload = self.client.post(
            "/api/files/",
            {
                "file": SimpleUploadedFile("enclosure.stl", b"solid enclosure\nendsolid enclosure\n"),
                "category": "mesh",
                "name": "Standalone enclosure",
            },
        )
        self.assertEqual(upload.status_code, 201, upload.content)
        asset_id = upload.json()["file"]["id"]

        response = self.client.patch(
            f"/api/files/{asset_id}/",
            data={
                "project_id": str(self.project.id),
                "name": "Project enclosure",
                "category": "mesh",
            },
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200, response.content)
        asset = FileAsset.objects.get(pk=asset_id)
        self.assertEqual(asset.project, self.project)
        self.assertEqual(asset.name, "Project enclosure")
        self.assertEqual(FileAsset.objects.filter(pk=asset_id).count(), 1)

    def test_standalone_file_delete_removes_stored_file(self):
        upload = self.client.post(
            "/api/files/",
            {
                "file": SimpleUploadedFile("notes.md", b"# Notes\n"),
                "category": "source",
                "name": "Notes",
            },
        )
        self.assertEqual(upload.status_code, 201, upload.content)
        asset = FileAsset.objects.get(name="Notes")
        stored_name = asset.file.name
        storage = asset.file.storage
        self.assertTrue(storage.exists(stored_name))

        response = self.client.delete(f"/api/files/{asset.id}/")
        self.assertEqual(response.status_code, 200)
        self.assertFalse(FileAsset.objects.filter(pk=asset.id).exists())
        self.assertFalse(storage.exists(stored_name))

    def test_uploading_new_file_version_preserves_history_and_shows_latest_only(self):
        first_payload = b"solid v1\nendsolid v1\n"
        upload = self.client.post(
            f"/api/projects/{self.project.id}/files/",
            {
                "file": SimpleUploadedFile("speaker-base.stl", first_payload, content_type="model/stl"),
                "category": "mesh",
                "name": "Speaker base",
                "version": "1.0",
            },
        )
        self.assertEqual(upload.status_code, 201, upload.content)
        first = FileAsset.objects.get(pk=upload.json()["file"]["id"])
        first_stored_name = first.file.name

        second_payload = b"solid v2\nendsolid v2\n"
        versioned = self.client.post(
            f"/api/files/{first.id}/versions/",
            {
                "file": SimpleUploadedFile("speaker-base-v1.1.stl", second_payload, content_type="model/stl"),
                "version": "1.1",
                "description": "Second printable revision",
            },
        )
        self.assertEqual(versioned.status_code, 201, versioned.content)
        second = FileAsset.objects.get(pk=versioned.json()["file"]["id"])
        self.assertEqual(second.supersedes_id, first.id)
        self.assertEqual(second.project_id, self.project.id)
        self.assertEqual(second.name, first.name)
        self.assertEqual(second.version, "1.1")
        self.assertTrue(first.file.storage.exists(first_stored_name))
        self.assertTrue(second.file.storage.exists(second.file.name))

        library = self.client.get("/api/files/")
        self.assertEqual(library.status_code, 200)
        self.assertEqual([row["id"] for row in library.json()["rows"]], [str(second.id)])

        detail = self.client.get(f"/api/projects/{self.project.id}/")
        self.assertEqual(detail.status_code, 200)
        self.assertEqual(detail.json()["project"]["file_count"], 1)
        self.assertEqual(detail.json()["project"]["files"][0]["id"], str(second.id))

        history = self.client.get(f"/api/files/{second.id}/versions/")
        self.assertEqual(history.status_code, 200)
        self.assertEqual(
            [item["version"] for item in history.json()["versions"]],
            ["1.1", "1.0"],
        )

        stale_upload = self.client.post(
            f"/api/files/{first.id}/versions/",
            {
                "file": SimpleUploadedFile("speaker-base-v1.2.stl", b"solid stale\nendsolid stale\n", content_type="model/stl"),
                "version": "1.2",
            },
        )
        self.assertEqual(stale_upload.status_code, 409)

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
