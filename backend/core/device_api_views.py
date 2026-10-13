"""Isolated bearer-only protocol for MakerVault hardware clients.

Never apply this authentication to existing browser/session API routes.
"""
from __future__ import annotations

import json
from datetime import timedelta
from functools import wraps

from django.http import JsonResponse
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

from .device_api_keys import parse_identifier, verify_token
from .models import MakerTag, UserApiKey
from .maker_tags import serialise_tag_target, resolve_tag_target, TARGETS, target_display
from .api_views import _sync_rfid_tag_to_spool, _record_tag_event

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
        "read_only": "tags:write" not in request.device_key.scopes,
        "key_name": request.device_key.name,
        "scopes": request.device_key.scopes,
        "capabilities": (["tags:resolve"] if "tags:read" in request.device_key.scopes else []) + (["tags:register", "tags:assign"] if "tags:write" in request.device_key.scopes else []) + (["records:search"] if "inventory:read" in request.device_key.scopes else []),
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
    definition = TARGETS.get(tag.target_type)
    if definition is None or not owner.has_perm(f"core.view_{definition.model._meta.model_name}"):
        return _error("Owner is not permitted to view the tagged record.", 403)
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


def _scan_payload(request, *, fields):
    if len(request.body) > MAX_JSON_BYTES:
        raise OverflowError("Request is too large.")
    try:
        data = json.loads(request.body)
    except (ValueError, UnicodeDecodeError) as exc:
        raise ValueError("Expected valid JSON.") from exc
    if not isinstance(data, dict) or set(data) != fields:
        raise ValueError("Unexpected or missing fields.")
    kind, uid = data.get("kind"), data.get("uid")
    if not isinstance(kind, str) or kind not in KINDS or not isinstance(uid, str):
        raise ValueError("Unsupported tag type or UID.")
    compact = uid.replace(":", "").replace("-", "").replace(" ", "")
    if len(compact) not in (8, 14, 20) or not all(c in "0123456789abcdefABCDEF" for c in compact):
        raise ValueError("UID must be 4, 7 or 10 hexadecimal bytes.")
    data["uid"] = compact.upper()
    return data


def _tag_summary(tag, owner):
    return {
        "id": str(tag.pk),
        "label": tag.label,
        "target": serialise_tag_target(owner, tag.target_type, tag.target_id),
    }


@require_http_methods(["GET"])
@require_device_scope("inventory:read")
def search_records(request):
    owner = request.device_owner
    target_type = request.GET.get("type", "")
    query = request.GET.get("q", "").strip().casefold()
    if target_type not in TARGETS or len(query) > 100:
        return _error("Choose a supported record type and a query of up to 100 characters.", 400)
    definition = TARGETS[target_type]
    perm = f"core.view_{definition.model._meta.model_name}"
    if not owner.has_perm(perm):
        return _error("Owner is not permitted to view these records.", 403)
    try:
        limit = int(request.GET.get("limit", "25"))
    except ValueError:
        return _error("Invalid result limit.", 400)
    if not 1 <= limit <= 50:
        return _error("Result limit must be between 1 and 50.", 400)
    # Stream candidates in batches so later records remain searchable; only
    # the requested limited number of results is ever returned to the device.
    candidates = definition.model.objects.filter(owner=owner).order_by("pk")
    if target_type == "inventory":
        candidates = candidates.select_related("board__manufacturer", "component")
    elif target_type == "spool":
        candidates = candidates.select_related("filament__filament_manufacturer", "filament__manufacturer")
    elif target_type == "reusable_spool":
        candidates = candidates.select_related("design")
    matches = []
    for obj in candidates.iterator(chunk_size=200):
        row = target_display(target_type, obj)
        if not query or query in (row["label"] + " " + row["subtitle"]).casefold():
            matches.append(row)
            if len(matches) >= limit:
                break
    return JsonResponse({"type": target_type, "rows": matches})


@require_http_methods(["POST"])
@require_device_scope("tags:write")
def register_tag(request):
    owner = request.device_owner
    if not owner.has_perm("core.add_makertag"):
        return _error("Owner is not permitted to create Maker Tags.", 403)
    try:
        data = _scan_payload(request, fields={"kind", "uid", "target_type", "target_id"})
        target = resolve_tag_target(owner, data["target_type"], data["target_id"])
        definition = TARGETS[data["target_type"]]
        if not owner.has_perm(f"core.view_{definition.model._meta.model_name}"):
            return _error("Owner is not permitted to view the selected record.", 403)
        with transaction.atomic():
            existing = MakerTag.objects.select_for_update().filter(
                kind=data["kind"], code=data["uid"],
            ).first()
            if existing:
                if existing.owner_id == owner.pk and existing.status == "active" and (
                    existing.target_type == data["target_type"] and existing.target_id == target.pk
                ):
                    return JsonResponse({"created": False, "item": _tag_summary(existing, owner)})
                return _error("Tag identity is already in use; registration cannot overwrite it.", 409)
            tag = MakerTag(
                owner=owner, kind=data["kind"], code=data["uid"],
                target_type=data["target_type"], target_id=target.pk,
            )
            tag.full_clean()
            tag.save()
            _sync_rfid_tag_to_spool(tag)
            _record_tag_event(tag, owner, "created", "Registered physical tag from device.", {
                "target_type": tag.target_type, "target_id": str(tag.target_id),
            })
        response = JsonResponse({"created": True, "item": _tag_summary(tag, owner)}, status=201)
        return response
    except OverflowError:
        return _error("Request is too large.", 413)
    except ValidationError:
        return _error("Invalid target or tag assignment, or conflicting spool UID.", 400)
    except (ValueError, TypeError):
        return _error("Invalid registration payload.", 400)
    except IntegrityError:
        return _error("Tag identity is already in use.", 409)


@require_http_methods(["POST"])
@require_device_scope("tags:write")
def assign_tag(request):
    owner = request.device_owner
    if not owner.has_perm("core.change_makertag"):
        return _error("Owner is not permitted to reassign Maker Tags.", 403)
    try:
        data = _scan_payload(request, fields={"kind", "uid", "target_type", "target_id"})
        target = resolve_tag_target(owner, data["target_type"], data["target_id"])
        definition = TARGETS[data["target_type"]]
        if not owner.has_perm(f"core.view_{definition.model._meta.model_name}"):
            return _error("Owner is not permitted to view the selected record.", 403)
        with transaction.atomic():
            tag = MakerTag.objects.select_for_update().filter(
                owner=owner, kind=data["kind"], code=data["uid"],
                status="active",
            ).first()
            if not tag:
                return _error("An active owned tag was not found. Register it first.", 404)
            if tag.target_type == data["target_type"] and tag.target_id == target.pk:
                return JsonResponse({"changed": False, "item": _tag_summary(tag, owner)})
            previous = {
                "kind": tag.kind, "code": tag.code,
                "target_type": tag.target_type, "target_id": str(tag.target_id),
                "status": tag.status,
            }
            tag.target_type, tag.target_id = data["target_type"], target.pk
            tag.full_clean()
            tag.save()
            _sync_rfid_tag_to_spool(tag, previous=previous)
            _record_tag_event(tag, owner, "reassigned", "Reassigned physical tag from device.", {
                "previous": previous,
                "target_type": tag.target_type, "target_id": str(tag.target_id),
            })
        return JsonResponse({"changed": True, "item": _tag_summary(tag, owner)})
    except OverflowError:
        return _error("Request is too large.", 413)
    except ValidationError:
        return _error("Invalid target or tag assignment, or conflicting spool UID.", 400)
    except (ValueError, TypeError):
        return _error("Invalid assignment payload.", 400)
    except IntegrityError:
        return _error("Tag assignment conflicts with another record.", 409)
