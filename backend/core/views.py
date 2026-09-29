import logging
import mimetypes
from pathlib import Path

import magic
from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.core.cache import cache
from django.db import connection
from django.http import FileResponse, Http404, JsonResponse
from django.shortcuts import render
from django.views.decorators.csrf import ensure_csrf_cookie
from .models import FileAsset, InventoryItem, Project

logger = logging.getLogger(__name__)


@login_required
@ensure_csrf_cookie
def app_shell(request):
    return render(request, "core/app.html")


@login_required
def media_file(request, path):
    # Private media is authorised by database ownership. The storage backend
    # transparently decrypts authenticated blobs; raw encrypted bytes are never
    # returned by this view.
    normalised = str(path or "").lstrip("/")
    private_prefix = normalised.startswith(("private/", "files/", "projects/covers/", "inventory/"))

    asset = FileAsset.objects.filter(owner=request.user, file=normalised).first()
    project = None if asset else Project.objects.filter(owner=request.user, cover_image=normalised).first()
    inventory = None if asset or project else InventoryItem.objects.filter(owner=request.user, image=normalised).first()

    if asset or project or inventory:
        field = asset.file if asset else project.cover_image if project else inventory.image
        try:
            stream = field.storage.open(field.name, "rb")
        except (FileNotFoundError, OSError, ValueError):
            raise Http404

        if asset:
            metadata = asset.metadata or {}
            download_name = Path(str(metadata.get("original_name") or asset.name or "file")).name
        elif project:
            download_name = "project-cover"
        else:
            download_name = "inventory-image"

        try:
            head = stream.read(4096)
            stream.seek(0)
            content_type = magic.from_buffer(head, mime=True) if head else None
        except Exception:
            try:
                stream.seek(0)
            except Exception:
                pass
            content_type, _ = mimetypes.guess_type(download_name)

        inline_types = {"image/png", "image/jpeg", "image/webp", "image/gif"}
        return FileResponse(
            stream,
            as_attachment=content_type not in inline_types,
            filename=download_name,
            content_type=content_type or "application/octet-stream",
        )

    # A private-looking path with no owned database record is never served. This
    # also blocks possession of another user's opaque object name from becoming
    # an access mechanism.
    if private_prefix:
        raise Http404

    # Shared catalogue/reference media remains ordinary authenticated media.
    root = settings.MEDIA_ROOT.resolve()
    requested = (root / normalised).resolve()
    try:
        requested.relative_to(root)
    except ValueError as exc:
        raise Http404 from exc
    if not requested.is_file():
        raise Http404

    content_type, _ = mimetypes.guess_type(requested.name)
    inline_types = {"image/png", "image/jpeg", "image/webp", "image/gif"}
    return FileResponse(
        requested.open("rb"),
        as_attachment=content_type not in inline_types,
        filename=requested.name,
        content_type=content_type or "application/octet-stream",
    )


def healthz(request):
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            cursor.fetchone()
        cache.set("makervault-health", "ok", timeout=10)
        if cache.get("makervault-health") != "ok":
            raise RuntimeError("Redis cache round-trip failed")
        return JsonResponse({"status": "ok"})
    except Exception:
        logger.exception("MakerVault health check failed")
        return JsonResponse({"status": "error"}, status=503)
