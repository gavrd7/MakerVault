import uuid
from contextlib import contextmanager

from django.contrib.auth.decorators import login_required
from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone
from django.http import HttpResponse, JsonResponse
from django.views.decorators.http import require_http_methods

from .api_views import _error, _read_json, _require_permission
from .models import PrinterConnection
from .printer_cameras import CameraError, discover_result, frame, negotiate, normalise_source, sources, provider_info, setup_presets


def connection_for(request, printer_id, connection_id):
    return PrinterConnection.objects.select_related("printer").filter(pk=connection_id, printer_id=printer_id, printer__owner=request.user).first()


def private_response(response):
    response["Cache-Control"] = "private, no-store, max-age=0"
    response["X-Content-Type-Options"] = "nosniff"
    response["Cross-Origin-Resource-Policy"] = "same-origin"
    return response


@contextmanager
def camera_slot(user_id, connection_id):
    key = f"camera-request:{user_id}:{connection_id}"
    token = uuid.uuid4().hex
    try:
        acquired = cache.add(key, token, timeout=20)
    except Exception as exc:
        raise CameraError("Camera request limiter is unavailable. Try again shortly.") from exc
    if not acquired:
        raise CameraError("Another camera request for this printer is active. Try again shortly.")
    try:
        yield
    finally:
        try:
            if cache.get(key) == token:
                cache.delete(key)
        except Exception:
            pass


@login_required
@require_http_methods(["GET", "POST", "PATCH", "DELETE"])
def camera_sources(request, printer_id, connection_id):
    connection = connection_for(request, printer_id, connection_id)
    if not connection:
        return _error("Printer source not found.", 404)
    if request.method == "GET":
        can_edit = request.user.has_perm("core.change_printer")
        return private_response(JsonResponse({"rows": [{key: value for key, value in item.items() if key != "url" or can_edit} for item in sources(connection)], "can_edit": can_edit, "provider": provider_info(connection), "presets": setup_presets(connection) if can_edit else []}))
    denied = _require_permission(request, "core.change_printer")
    if denied:
        return denied
    try:
        payload = _read_json(request)
        with transaction.atomic():
            connection = PrinterConnection.objects.select_for_update().get(pk=connection.pk)
            config = dict(connection.config or {})
            rows = sources(connection)
            if request.method == "DELETE":
                rows = [item for item in rows if item["id"] != str(payload.get("id") or "")]
            elif request.method == "PATCH":
                selected_id = str(payload.get("id") or "")
                if not any(row["id"] == selected_id for row in rows):
                    return _error("Camera source not found.", 404)
                config["camera_default_id"] = selected_id
            else:
                if len(rows) >= 8:
                    return _error("A printer source can have up to eight cameras.")
                rows.append(normalise_source(connection, payload, uuid.uuid4().hex))
                config["camera_default_id"] = rows[-1]["id"]
            config["camera_configured_at"] = timezone.now().isoformat()
            config["cameras"] = rows
            connection.config = config
            connection.save(update_fields=["config", "updated_at"])
        return private_response(JsonResponse({"saved": True}))
    except (CameraError, TypeError, ValueError, ValidationError) as exc:
        return _error(str(exc) if isinstance(exc, CameraError) else "Invalid camera configuration.")


@login_required
@require_http_methods(["POST"])
def camera_discover(request, printer_id, connection_id):
    denied = _require_permission(request, "core.change_printer")
    if denied:
        return denied
    connection = connection_for(request, printer_id, connection_id)
    if not connection:
        return _error("Printer source not found.", 404)
    if not connection.enabled:
        return _error("Enable this printer source before camera discovery.")
    try:
        with camera_slot(request.user.pk, connection.pk):
            result = discover_result(connection)
        return private_response(JsonResponse(result))
    except (CameraError, TypeError, ValueError, AttributeError) as exc:
        return _error(str(exc) if isinstance(exc, CameraError) else "Camera discovery returned an unsupported response.", 502)


@login_required
@require_http_methods(["GET", "POST"])
def camera_media(request, printer_id, connection_id, camera_id):
    connection = connection_for(request, printer_id, connection_id)
    if not connection:
        return _error("Printer source not found.", 404)
    if not connection.enabled:
        return _error("This printer source is disabled.", 409)
    source = next((item for item in sources(connection) if item["id"] == camera_id), None)
    if not source:
        return _error("Camera source not found.", 404)
    try:
        with camera_slot(request.user.pk, connection.pk):
            if request.method == "POST":
                if request.META.get("CONTENT_LENGTH", "0").isdigit() and int(request.META.get("CONTENT_LENGTH", "0")) > 70000:
                    return _error("Camera offer is too large.", 413)
                answer = negotiate(connection, source, _read_json(request).get("sdp"))
                return private_response(JsonResponse(answer))
            data, content_type = frame(connection, source)
            return private_response(HttpResponse(data, content_type=content_type))
    except (CameraError, ValidationError, TypeError, ValueError) as exc:
        return private_response(_error(str(exc) if isinstance(exc, CameraError) else "Invalid camera request.", 502))
