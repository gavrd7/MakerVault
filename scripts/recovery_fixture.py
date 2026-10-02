"""Synthetic recovery acceptance data; executed only by recovery_rehearsal.sh."""
import hashlib
import os

from django.contrib.auth import get_user_model
from django.core.files.base import ContentFile
from django.core.management import call_command
from django.test import Client, override_settings

from core.models import FileAsset, InventoryItem, Model3D, ModelRevision, ModelRevisionAsset, Project

if os.environ.get("MAKERVAULT_RECOVERY_REHEARSAL") != "synthetic-only":
    raise RuntimeError("This fixture is only for disposable recovery rehearsals")

User = get_user_model()
payloads = [b"solid recovered revision one\nendsolid\n", b"solid recovered revision two\nendsolid\n"]
password = "synthetic-recovery-password-only"
if os.environ["RECOVERY_PHASE"] == "seed":
    if User.objects.exists() or Project.objects.exists() or FileAsset.objects.exists():
        raise RuntimeError("Refusing to seed a nonempty database")
    owner = User.objects.create_user(username="recovery-owner", password=password)
    User.objects.create_user(username="recovery-other", password=password)
    project = Project.objects.create(owner=owner, name="Recovery project")
    InventoryItem.objects.create(owner=owner, project=project, inventory_id="RECOVERY-001", item_type="other", quantity=3)
    model = Model3D.objects.create(owner=owner, project=project, name="Recovery model")
    previous = None
    for index, payload in enumerate(payloads, 1):
        asset = FileAsset.objects.create(
            owner=owner, project=project, name=f"revision-{index}.stl", category="mesh",
            file=ContentFile(payload, name=f"revision-{index}.stl"),
            sha256=hashlib.sha256(payload).hexdigest(), supersedes=previous,
        )
        revision = ModelRevision.objects.create(model=model, version=str(index))
        ModelRevisionAsset.objects.create(revision=revision, file_asset=asset, is_primary=True)
        previous = asset
else:
    owner = User.objects.get(username="recovery-owner")
    assert owner.check_password(password)
    project = Project.objects.get(owner=owner, name="Recovery project")
    assert InventoryItem.objects.get(owner=owner, inventory_id="RECOVERY-001").project_id == project.pk
    assert InventoryItem.objects.get(owner=owner, inventory_id="RECOVERY-001").quantity == 3
    model = Model3D.objects.get(owner=owner, project=project, name="Recovery model")
    assert model.revisions.count() == 2
    previous = None
    with override_settings(
        ALLOWED_HOSTS=["testserver"], SECURE_SSL_REDIRECT=False,
        CACHES={"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}},
    ):
        client = Client()
        assert client.login(username=owner.username, password=password)
        for index, payload in enumerate(payloads, 1):
            asset = FileAsset.objects.get(owner=owner, name=f"revision-{index}.stl")
            assert asset.project_id == project.pk
            assert asset.supersedes_id == previous
            assert ModelRevisionAsset.objects.get(revision__model=model, revision__version=str(index)).file_asset_id == asset.pk
            response = client.get(asset.file.url)
            assert response.status_code == 200, response.status_code
            assert b"".join(response.streaming_content) == payload
            previous = asset.pk
        client.logout()
        assert client.login(username="recovery-other", password=password)
        assert client.get(asset.file.url).status_code == 404
    call_command("audit_private_ownership", fail_on_issues=True)
    call_command("verify_private_storage")
    print("Recovery accepted: password login, project/model links, old/current downloads and owner isolation.")
