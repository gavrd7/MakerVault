"""Read-only, owner-scoped browser-to-handheld Maker Tag lookup."""
import json
import uuid
from datetime import timedelta

from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.http import JsonResponse
from django.utils import timezone
from django.views.decorators.http import require_http_methods

from .device_api_views import require_device_scope, _scan_payload
from .device_tag_registration import failure
from .maker_tags import TARGETS, serialise_tag_target
from .models import ConnectedDevice, DeviceTagLookup, DeviceTagRegistration, MakerTag
from .radio_tag_identity import radio_tag_matches

TTL = timedelta(minutes=5)


def result(item):
    expired = item.state == "pending" and item.expires_at <= timezone.now()
    state = "expired" if expired else item.state
    tag = item.tag
    target = None
    if state == "completed" and tag is not None:
        definition = TARGETS.get(tag.target_type)
        if definition and item.owner.has_perm(f"core.view_{definition.model._meta.model_name}"):
            target = serialise_tag_target(item.owner, tag.target_type, tag.target_id)
    return {
        "id": str(item.id), "state": state, "expires_at": item.expires_at.isoformat(),
        "device_id": str(item.device_id), "found": item.found if state == "completed" else None,
        "uid": item.scanned_uid if state == "completed" else "",
        "tag": {"id": str(tag.pk), "label": tag.label, "target": target}
        if tag is not None and target is not None and state == "completed" else None,
    }


@login_required
@require_http_methods(["POST"])
def begin(request):
    if not (request.is_secure() or settings.DEBUG):
        return failure("HTTPS required.", 403)
    if not request.user.has_perm("core.view_makertag"):
        return failure("Insufficient Maker Tag permissions.", 403)
    try:
        if len(request.body) > 1024:
            return failure("Request is too large.", 413)
        payload = json.loads(request.body)
        if not isinstance(payload, dict) or set(payload) != {"device_id"}:
            return failure("Provide device_id.")
        device_id = uuid.UUID(str(payload["device_id"]))
    except (ValueError, TypeError, KeyError):
        return failure("Invalid lookup request.")
    with transaction.atomic():
        device = ConnectedDevice.objects.select_for_update(of=("self",)).select_related("api_key").filter(
            pk=device_id, owner=request.user, device_type="rfid_terminal", revoked_at__isnull=True
        ).first()
        if not device or not device.api_key or not device.api_key.is_active():
            return failure("Active paired terminal not found.", 404)
        if "tags:read" not in device.api_key.scopes:
            return failure("The terminal requires tags:read.", 403)
        if DeviceTagLookup.objects.filter(device=device, state="pending", expires_at__gt=timezone.now()).exists() or DeviceTagRegistration.objects.filter(
            device=device, state="pending", expires_at__gt=timezone.now()
        ).exists():
            return failure("The terminal already has a pending scan request.", 409)
        item = DeviceTagLookup.objects.create(owner=request.user, device=device, expires_at=timezone.now() + TTL)
    return JsonResponse(result(item), status=201)


@login_required
@require_http_methods(["GET"])
def status(request, lookup_id):
    item = DeviceTagLookup.objects.select_related("tag").filter(pk=lookup_id, owner=request.user).first()
    return JsonResponse(result(item)) if item else failure("Lookup not found.", 404)


@login_required
@require_http_methods(["POST"])
def cancel(request, lookup_id):
    if not (request.is_secure() or settings.DEBUG):
        return failure("HTTPS required.", 403)
    with transaction.atomic():
        item = DeviceTagLookup.objects.select_for_update().filter(pk=lookup_id, owner=request.user).first()
        if item is None:
            return failure("Lookup not found.", 404)
        if item.state != "pending" or item.expires_at <= timezone.now():
            return failure("Lookup is no longer pending.", 409)
        item.state = "cancelled"
        item.save(update_fields=["state", "updated_at"])
    return JsonResponse(result(item))


def paired(request):
    return ConnectedDevice.objects.filter(
        owner=request.device_owner, api_key=request.device_key, device_type="rfid_terminal",
        revoked_at__isnull=True
    ).first()


@require_http_methods(["GET"])
@require_device_scope("tags:read")
def pending(request):
    device = paired(request)
    if device is None:
        return failure("Active paired terminal required.", 403)
    item = DeviceTagLookup.objects.filter(device=device, state="pending", expires_at__gt=timezone.now()).order_by("-created_at").first()
    return JsonResponse({"lookup": {"id": str(item.id)} if item else None})


@require_http_methods(["POST"])
@require_device_scope("tags:read")
def complete(request, lookup_id):
    device = paired(request)
    if device is None:
        return failure("Active paired terminal required.", 403)
    if not request.device_owner.has_perm("core.view_makertag"):
        return failure("Insufficient Maker Tag permissions.", 403)
    try:
        data = _scan_payload(request, fields={"kind", "uid"})
    except OverflowError:
        return failure("Request is too large.", 413)
    except (ValueError, TypeError):
        return failure("Invalid scanned UID.")
    with transaction.atomic():
        item = DeviceTagLookup.objects.select_for_update(of=("self",)).select_related("tag").filter(
            pk=lookup_id, owner=request.device_owner, device=device
        ).first()
        if item is None:
            return failure("Lookup not found.", 404)
        if item.state == "completed":
            if item.scanned_uid == data["uid"]:
                return JsonResponse(result(item))
            return failure("Lookup already completed with another UID.", 409)
        if item.state != "pending" or item.expires_at <= timezone.now():
            return failure("Lookup cancelled or expired.", 410)
        matches = list(radio_tag_matches(MakerTag.objects.filter(owner=request.device_owner, status="active"), data["kind"], data["uid"])[:2])
        if len(matches) > 1:
            return failure("Ambiguous historical NFC/RFID identity.", 409)
        tag = matches[0] if matches else None
        if tag:
            definition = TARGETS.get(tag.target_type)
            if not definition or not request.device_owner.has_perm(f"core.view_{definition.model._meta.model_name}"):
                return failure("Insufficient record permissions.", 403)
        item.state = "completed"
        item.completed_at = timezone.now()
        item.scanned_uid = data["uid"]
        item.found = tag is not None
        item.tag = tag
        item.save(update_fields=["state", "completed_at", "scanned_uid", "found", "tag", "updated_at"])
    return JsonResponse(result(item), status=201)
