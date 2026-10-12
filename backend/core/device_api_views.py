"""Isolated bearer-only, read-only protocol for MakerVault hardware clients.

Never apply this authentication to existing browser/session API routes.
"""
from __future__ import annotations

import json
from datetime import timedelta
from functools import wraps

from django.http import JsonResponse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

from .device_api_keys import parse_identifier, verify_token
from .models import MakerTag, UserApiKey
from .maker_tags import serialise_tag_target

MAX_JSON_BYTES = 1024
KINDS = {"nfc", "rfid"}


def _error(message, status):
    response = JsonResponse({"error": message}, status=status)
    response["Cache-Control"] = "no-store"
    return response


def require_device_scope(scope):
    """Require a valid Bearer key; session cookies are never sufficient."""
    def decorator(view):
        @csrf_exempt
        @wraps(view)
        def guarded(request, *args, **kwargs):
            header = request.headers.get("Authorization", "")
            if not header.startswith("Bearer ") or header.count(" ") != 1:
                return _error("Bearer API key required.", 401)
            credential = header[7:]
            identifier = parse_identifier(credential)
            if identifier is None:
                return _error("Invalid API key.", 401)
            key = UserApiKey.objects.select_related("owner").filter(identifier=identifier).first()
            if key is None or not verify_token(credential, key.secret_digest) or not key.is_active():
                return _error("Invalid or inactive API key.", 401)
            if scope not in key.scopes:
                return _error("API key does not allow this action.", 403)
            request.device_key = key
            request.device_owner = key.owner
            response = view(request, *args, **kwargs)
            if key.last_used_at is None or key.last_used_at < timezone.now() - timedelta(minutes=5):
                UserApiKey.objects.filter(pk=key.pk, revoked_at__isnull=True).update(last_used_at=timezone.now())
            response["Cache-Control"] = "no-store"
            return response
        return guarded
    return decorator


@require_http_methods(["GET"])
@require_device_scope("tags:read")
def device_me(request):
    return JsonResponse({
        "protocol": "makervault-device-v1",
        "read_only": True,
        "key_name": request.device_key.name,
        "scopes": request.device_key.scopes,
        "capabilities": ["tags:resolve"],
    })


@require_http_methods(["POST"])
@require_device_scope("tags:read")
def resolve_tag(request):
    owner = request.device_owner
    if not owner.has_perm("core.view_makertag"):
        return _error("Owner is not permitted to view Maker Tags.", 403)
    if len(request.body) > MAX_JSON_BYTES:
        return _error("Request is too large.", 413)
    try:
        payload = json.loads(request.body)
    except (ValueError, UnicodeDecodeError):
        return _error("Expected a JSON object.", 400)
    if not isinstance(payload, dict) or set(payload) != {"kind", "uid"}:
        return _error("Provide kind and uid.", 400)
    kind = payload["kind"]
    uid = payload["uid"]
    if not isinstance(kind, str) or kind not in KINDS or not isinstance(uid, str):
        return _error("Unsupported tag type or UID.", 400)
    compact = uid.replace(":", "").replace("-", "").replace(" ", "")
    if not (len(compact) in (8, 14, 20) and all(c in "0123456789abcdefABCDEF" for c in compact)):
        return _error("UID must be a 4, 7 or 10-byte hexadecimal value.", 400)
    code = compact.upper()
    tag = MakerTag.objects.filter(owner=owner, kind=kind, code=code, status="active").first()
    if tag is None:
        return JsonResponse({"found": False, "status": "unregistered", "kind": kind, "uid": code})
    target = serialise_tag_target(owner, tag.target_type, tag.target_id)
    if target is None:
        return _error("The tag target is no longer available.", 404)
    return JsonResponse({
        "found": True,
        "status": "identified",
        "kind": kind,
        "uid": code,
        "tag": {"id": str(tag.pk), "label": tag.label, "target": target},
    })
