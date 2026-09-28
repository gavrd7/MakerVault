import logging
import mimetypes
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
    # Private media must be authorised by database ownership, not merely by
    # possession of a MEDIA_URL path. Unknown files under private prefixes are
    # intentionally treated as not found so stale/orphaned blobs cannot leak.
    normalised = str(path or "").lstrip("/")
    if normalised.startswith("files/"):
        allowed = FileAsset.objects.filter(owner=request.user, file=normalised).exists()
        if not allowed:
            raise Http404
    elif normalised.startswith("projects/covers/"):
        allowed = Project.objects.filter(owner=request.user, cover_image=normalised).exists()
        if not allowed:
            raise Http404
    elif normalised.startswith("inventory/"):
        allowed = InventoryItem.objects.filter(owner=request.user, image=normalised).exists()
        if not allowed:
            raise Http404

    root = settings.MEDIA_ROOT.resolve()
    requested = (root / path).resolve()
    try:
        requested.relative_to(root)
    except ValueError as exc:
        raise Http404 from exc
    if not requested.is_file():
        raise Http404

    content_type, _ = mimetypes.guess_type(requested.name)
    # Only raster images are displayed inline. Everything else is download-only,
    # preventing active uploads such as SVGs or executables from running in the
    # MakerVault origin.
    inline_types = {"image/png", "image/jpeg", "image/webp", "image/gif"}
    as_attachment = content_type not in inline_types
    return FileResponse(
        requested.open("rb"),
        as_attachment=as_attachment,
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
