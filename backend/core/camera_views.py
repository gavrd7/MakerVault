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
from .camera_relay import CameraRelayError, hls_master, hls_resource
from .models import PrinterConnection
from .printer_cameras import CameraError, discover_result, frame, negotiate, normalise_source, sources, provider_info, setup_presets


def connection_for(request, printer_id, connection_id):
    return PrinterConnection.objects.select_related("printer").filter(pk=connection_id, printer_id=printer_id, printer__owner=request.user).first()


def private_response(response):
    response["Cache-Control"] = "private, no-store, max-age=0"
    response["X-Content-Type-Options"] = "nosniff"
    response["Cross-Origin-Resource-Policy"] = "same-origin"
    return response


def _remove_camera_source(connection, camera_id):
    config = dict(connection.config or {})
    raw = config.get("cameras", [])
    if not isinstance(raw, list):
        raw = []
    if not any(isinstance(item, dict) and item.get("id") == camera_id for item in raw):
        raise CameraError("Camera source not found.")

    raw = [
        item for item in raw
        if not (isinstance(item, dict) and item.get("id") == camera_id)
    ]
    config["cameras"] = raw
    connection.config = config
    remaining = sources(connection)
    if config.get("camera_default_id") == camera_id or not any(
        item["id"] == config.get("camera_default_id") for item in remaining
    ):
        if remaining:
            config["camera_default_id"] = remaining[-1]["id"]
        else:
            config.pop("camera_default_id", None)
    config["camera_configured_at"] = timezone.now().isoformat()
    connection.config = config
    connection.save(update_fields=["config", "updated_at"])
    return sources(connection)


@contextmanager
def camera_slot(user_id):
    key = f"camera-request:{user_id}"
    token = uuid.uuid4().hex
    try:
        acquired = cache.add(key, token, timeout=20)
    except Exception as exc:
        raise CameraError("Camera request limiter is unavailable. Try again shortly.") from exc
    if not acquired:
        raise CameraError("Another camera request is active. Try again shortly.")
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
                candidate = normalise_source(connection, payload, uuid.uuid4().hex)
                existing = next(
                    (item for item in rows if item["mode"] == candidate["mode"] and item["url"] == candidate["url"]),
                    None,
                )
                if existing:
                    candidate = normalise_source(connection, payload, existing["id"])
                    rows = [
                        candidate if item["id"] == existing["id"] else item
                        for item in rows
                        if item["id"] == existing["id"]
                        or not (item["mode"] == candidate["mode"] and item["url"] == candidate["url"])
                    ]
                    config["camera_default_id"] = existing["id"]
                else:
                    if len(rows) >= 8:
                        return _error("A printer source can have up to eight cameras.")
                    rows.append(candidate)
                    config["camera_default_id"] = candidate["id"]
            config["camera_configured_at"] = timezone.now().isoformat()
            config["cameras"] = rows
            connection.config = config
            connection.save(update_fields=["config", "updated_at"])
        return private_response(JsonResponse({"saved": True}))
    except (CameraError, TypeError, ValueError, ValidationError) as exc:
        return _error(str(exc) if isinstance(exc, CameraError) else "Invalid camera configuration.")


@login_required
@require_http_methods(["POST"])
def camera_source_remove(request, printer_id, connection_id, camera_id):
    connection = connection_for(request, printer_id, connection_id)
    if not connection:
        return _error("Printer source not found.", 404)
    denied = _require_permission(request, "core.change_printer")
    if denied:
        return denied
    try:
        with transaction.atomic():
            connection = PrinterConnection.objects.select_for_update().get(pk=connection.pk)
            rows = _remove_camera_source(connection, camera_id)
        return private_response(JsonResponse({"deleted": True, "id": camera_id, "rows": rows}))
    except CameraError as exc:
        return _error(str(exc), 404)


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
        with camera_slot(request.user.pk):
            result = discover_result(connection)
        return private_response(JsonResponse(result))
    except (CameraError, TypeError, ValueError, AttributeError) as exc:
        return _error(str(exc) if isinstance(exc, CameraError) else "Camera discovery returned an unsupported response.", 502)


def _hls_session_key(user_id, connection_id, camera_id, session_id):
    return f"camera-hls:{user_id}:{connection_id}:{camera_id}:{session_id}"


def _hls_camera(request, printer_id, connection_id, camera_id):
    connection = connection_for(request, printer_id, connection_id)
    if not connection:
        return None, None, _error("Printer source not found.", 404)
    if not connection.enabled:
        return None, None, _error("This printer source is disabled.", 409)
    source = next((item for item in sources(connection) if item["id"] == camera_id), None)
    if not source:
        return None, None, _error("Camera source not found.", 404)
    if source.get("mode") != "creality_webrtc":
        return None, None, _error("This camera source does not use the protected K2 relay.", 400)
    return connection, source, None


def _playlist_session_ids(text):
    ids = []
    for line in text.replace("\r\n", "\n").split("\n"):
        if line.startswith("#") or "id=" not in line:
            continue
        query = line.split("?", 1)[1] if "?" in line else ""
        for part in query.split("&"):
            if part.startswith("id="):
                value = part[3:]
                if value and len(value) <= 128 and all(ch.isalnum() or ch in "_-" for ch in value):
                    ids.append(value)
    return ids


def _rewrite_hls_playlist(text, expected_resource=None):
    rewritten = []
    for line in text.replace("\r\n", "\n").split("\n"):
        if not line or line.startswith("#"):
            rewritten.append(line)
            continue
        query = line.split("?", 1)[1] if "?" in line else ""
        session_id = ""
        for part in query.split("&"):
            if part.startswith("id="):
                session_id = part[3:]
                break
        if not session_id:
            rewritten.append(line)
            continue
        if expected_resource:
            resource = expected_resource
        else:
            resource = line.split("?", 1)[0].rstrip("/").split("/")[-1]
            if resource not in {"playlist.m3u8", "init.mp4", "segment.m4s", "segment.ts"}:
                rewritten.append(line)
                continue
        rewritten.append(f"{resource}?id={session_id}")
    return "\n".join(rewritten)


@login_required
@require_http_methods(["GET"])
def camera_hls_master(request, printer_id, connection_id, camera_id):
    connection, _source, error = _hls_camera(request, printer_id, connection_id, camera_id)
    if error:
        return private_response(error)
    try:
        playlist = hls_master(connection.pk, camera_id)
        session_ids = _playlist_session_ids(playlist)
        if not session_ids:
            raise CameraRelayError("The camera relay did not create an HLS session.")
        for session_id in session_ids:
            cache.set(
                _hls_session_key(request.user.pk, connection.pk, camera_id, session_id),
                True,
                timeout=120,
            )
        response = HttpResponse(
            _rewrite_hls_playlist(playlist, expected_resource="playlist.m3u8"),
            content_type="application/vnd.apple.mpegurl",
        )
        return private_response(response)
    except (CameraRelayError, CameraError, ValidationError, TypeError, ValueError) as exc:
        message = str(exc) if isinstance(exc, (CameraRelayError, CameraError)) else "Invalid camera relay request."
        return private_response(_error(message, 502))


@login_required
@require_http_methods(["GET"])
def camera_hls_resource(request, printer_id, connection_id, camera_id, resource):
    connection, _source, error = _hls_camera(request, printer_id, connection_id, camera_id)
    if error:
        return private_response(error)
    session_id = str(request.GET.get("id") or "")
    key = _hls_session_key(request.user.pk, connection.pk, camera_id, session_id)
    try:
        if not session_id or cache.get(key) is not True:
            return private_response(_error("Camera relay session expired. Reconnect the camera.", 403))
        cache.set(key, True, timeout=120)
        data, content_type = hls_resource(session_id, resource)
        if resource == "playlist.m3u8":
            try:
                text = data.decode("utf-8")
            except UnicodeDecodeError as exc:
                raise CameraRelayError("The camera relay returned an invalid HLS playlist.") from exc
            data = _rewrite_hls_playlist(text).encode("utf-8")
            content_type = "application/vnd.apple.mpegurl"
        response = HttpResponse(data, content_type=content_type)
        return private_response(response)
    except (CameraRelayError, CameraError, ValidationError, TypeError, ValueError) as exc:
        message = str(exc) if isinstance(exc, (CameraRelayError, CameraError)) else "Invalid camera relay request."
        return private_response(_error(message, 502))


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
        with camera_slot(request.user.pk):
            if request.method == "POST":
                if request.META.get("CONTENT_LENGTH", "0").isdigit() and int(request.META.get("CONTENT_LENGTH", "0")) > 70000:
                    return _error("Camera offer is too large.", 413)
                answer = negotiate(connection, source, _read_json(request).get("sdp"))
                return private_response(JsonResponse(answer))
            data, content_type = frame(connection, source)
            return private_response(HttpResponse(data, content_type=content_type))
    except (CameraError, ValidationError, TypeError, ValueError) as exc:
        return private_response(_error(str(exc) if isinstance(exc, CameraError) else "Invalid camera request.", 502))
