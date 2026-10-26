"""Secure browser-to-paired-terminal Maker Tag registration workflow."""
import json
import uuid
from datetime import timedelta

from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.http import JsonResponse
from django.utils import timezone
from django.views.decorators.http import require_http_methods

from .device_api_views import require_device_scope, _scan_payload, _tag_summary
from .models import ConnectedDevice, DeviceTagRegistration, MakerTag
from .maker_tags import TARGETS, resolve_tag_target, serialise_tag_target
from .api_views import _sync_rfid_tag_to_spool, _record_tag_event

TTL = timedelta(minutes=5)
SUPPORTED = {"inventory", "spool"}


def failure(message, status=400):
    result = JsonResponse({"error": message}, status=status)
    result["Cache-Control"] = "no-store"
    return result


def secure(request):
    return request.is_secure() or settings.DEBUG


def payload(request):
    if len(request.body) > 1024:
        raise ValueError("Payload exceeds 1024 bytes.")
    obj = json.loads(request.body)
    if not isinstance(obj, dict):
        raise ValueError("Expected a JSON object.")
    return obj


def summary(item):
    state = "expired" if item.state == "pending" and item.expires_at <= timezone.now() else item.state
    return {"id": str(item.pk), "state": state, "expires_at": item.expires_at.isoformat(),
            "device_id": str(item.device_id),
            "target": serialise_tag_target(item.owner, item.target_type, item.target_id),
            "tag": _tag_summary(item.tag, item.owner) if item.tag_id and item.tag else None}


@login_required
@require_http_methods(["POST"])
def begin(request):
    if not secure(request):
        return failure("HTTPS required.", 403)
    try:
        data = payload(request)
        if set(data) != {"device_id", "target_type", "target_id"}:
            raise ValueError("Provide device_id, target_type and target_id.")
        kind = data["target_type"]
        if kind not in SUPPORTED:
            raise ValueError("Unsupported target type.")
        device_id = uuid.UUID(str(data["device_id"]))
        target = resolve_tag_target(request.user, kind, data["target_id"])
        definition = TARGETS[kind]
        if not request.user.has_perm("core.add_makertag") or not request.user.has_perm(
            f"core.view_{definition.model._meta.model_name}"
        ):
            return failure("Insufficient permissions.", 403)
    except (ValueError, TypeError, ValidationError, KeyError, json.JSONDecodeError):
        return failure("Invalid registration request.")
    with transaction.atomic():
        device = ConnectedDevice.objects.select_for_update().select_related("api_key").filter(
            pk=device_id, owner=request.user, device_type="rfid_terminal", revoked_at__isnull=True
        ).first()
        if not device or not device.api_key or not device.api_key.is_active():
            return failure("Active paired RFID terminal not found.", 404)
        if "tags:write" not in device.api_key.scopes:
            return failure("The selected device requires tags:write permission.", 403)
        if DeviceTagRegistration.objects.filter(
            device=device, state="pending", expires_at__gt=timezone.now()
        ).exists():
            return failure("The terminal already has a pending registration.", 409)
        item = DeviceTagRegistration.objects.create(
            owner=request.user, device=device, target_type=kind,
            target_id=target.pk, expires_at=timezone.now() + TTL
        )
    return JsonResponse(summary(item), status=201)


@login_required
@require_http_methods(["GET"])
def status(request, registration_id):
    item = DeviceTagRegistration.objects.select_related("tag").filter(
        pk=registration_id, owner=request.user
    ).first()
    return JsonResponse(summary(item)) if item else failure("Registration not found.", 404)


@login_required
@require_http_methods(["POST"])
def cancel(request, registration_id):
    if not secure(request):
        return failure("HTTPS required.", 403)
    with transaction.atomic():
        item = DeviceTagRegistration.objects.select_for_update().filter(
            pk=registration_id, owner=request.user
        ).first()
        if not item:
            return failure("Registration not found.", 404)
        if item.state != "pending" or item.expires_at <= timezone.now():
            return failure("Registration is no longer pending.", 409)
        item.state = "cancelled"
        item.save(update_fields=["state", "updated_at"])
    return JsonResponse(summary(item))


def paired_device(request):
    return ConnectedDevice.objects.filter(
        owner=request.device_owner, api_key=request.device_key,
        device_type="rfid_terminal", revoked_at__isnull=True
    ).first()


@require_http_methods(["GET"])
@require_device_scope("tags:write")
def device_pending(request):
    device = paired_device(request)
    if not device:
        return failure("Active paired RFID terminal required.", 403)
    item = DeviceTagRegistration.objects.filter(
        device=device, state="pending", expires_at__gt=timezone.now()
    ).order_by("-created_at").first()
    return JsonResponse({"registration": summary(item) if item else None})


@require_http_methods(["POST"])
@require_device_scope("tags:write")
def device_complete(request, registration_id):
    device = paired_device(request)
    if not device:
        return failure("Active paired RFID terminal required.", 403)
    if not request.device_owner.has_perm("core.add_makertag"):
        return failure("Insufficient tag permissions.", 403)
    try:
        data = _scan_payload(request, fields={"kind", "uid"})
    except OverflowError:
        return failure("Request too large.", 413)
    except (ValueError, TypeError):
        return failure("Invalid scanned tag.")
    with transaction.atomic():
        item = DeviceTagRegistration.objects.select_for_update().select_related("tag").filter(
            pk=registration_id, device=device, owner=request.device_owner
        ).first()
        if not item:
            return failure("Registration not found.", 404)
        if item.state == "completed":
            if item.tag and item.tag.kind == data["kind"] and item.tag.code == data["uid"]:
                return JsonResponse(summary(item))
            return failure("Registration was already completed with another tag.", 409)
        if item.state != "pending" or item.expires_at <= timezone.now():
            return failure("Registration cancelled or expired.", 410)
        definition = TARGETS.get(item.target_type)
        if not definition or not request.device_owner.has_perm(
            f"core.view_{definition.model._meta.model_name}"
        ):
            return failure("Target access denied.", 403)
        try:
            # Savepoint keeps a failed tag insert from poisoning the enclosing\n            # transaction (including on PostgreSQL unique constraint errors).\n            with transaction.atomic():\n                target = resolve_tag_target(request.device_owner, item.target_type, item.target_id)
                if MakerTag.objects.select_for_update().filter(kind=data["kind"], code=data["uid"]).exists():
                    return failure("This physical tag is already registered.", 409)
                tag = MakerTag(owner=request.device_owner, kind=data["kind"], code=data["uid"],
                               target_type=item.target_type, target_id=target.pk)
                tag.full_clean()
                tag.save()
                _sync_rfid_tag_to_spool(tag)
                _record_tag_event(tag, request.device_owner, "created",
                                  "Registered from a paired RFID terminal.", {
                                      "device_id": str(device.pk), "request_id": str(item.pk)
                                  })
        except (ValidationError, ValueError):
            return failure("Tag identity or target conflicts with another record.", 409)
        except IntegrityError:
            return failure("Tag identity is already in use.", 409)
        item.tag = tag
        item.state = "completed"
        item.completed_at = timezone.now()
        item.save(update_fields=["tag", "state", "completed_at", "updated_at"])
    return JsonResponse(summary(item), status=201)
