"""Bounded MakerTag clean and remove requests for paired ESP32 terminals.

A clean never deletes a MakerTag. Combined remove is a two-phase operation:
NFC-cleared report is committed first, then an independently authorized
server-side deletion. A network error after the wipe is recoverable.
"""
import json
import uuid
from datetime import timedelta

from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.http import JsonResponse
from django.utils import timezone
from django.views.decorators.http import require_http_methods

from .device_api_views import require_device_scope
from .device_tag_operations_model import DeviceMakerTagOperation as Operation
from .models import (ConnectedDevice, MakerTag, DeviceNdefWrite,
                     DeviceTagRegistration, DeviceTagLookup)
from .radio_tag_identity import radio_tag_matches
from .api_views import _record_tag_event

TTL = timedelta(minutes=5)
CLEAN_CAPABILITY = "ntag215_ndef_write"


def failure(message, code=400):
    result = JsonResponse({"error": message}, status=code)
    result["Cache-Control"] = "no-store"
    return result


def json_payload(request, allowed):
    if len(request.body) > 1024:
        raise ValueError("Request too large.")
    data = json.loads(request.body or b"{}")
    if not isinstance(data, dict) or set(data) != allowed:
        raise ValueError("Unexpected operation request fields.")
    return data


def serialise(item):
    state = "expired" if item.state == "pending" and item.expires_at <= timezone.now() else item.state
    return {
        "id": str(item.id), "state": state, "source": item.source,
        "action": item.action, "also_clean": item.also_clean,
        "device_id": str(item.device_id), "uid": item.expected_uid,
        "maker_tag_id": "MV-" + item.expected_short_id,
        "tag_id": str(item.tag_id_snapshot),
        "target_type": item.target_type, "target_id": str(item.target_id),
        "label": item.tag.label if item.tag_id else "",
        "expires_at": item.expires_at.isoformat(),
        "cleaned_at": item.cleaned_at.isoformat() if item.cleaned_at else None,
    }


def response(item, code=200):
    result = JsonResponse({"operation": serialise(item)}, status=code)
    result["Cache-Control"] = "no-store"
    return result


def paired(request):
    return ConnectedDevice.objects.select_related("api_key").filter(
        owner=request.device_owner, api_key=request.device_key,
        revoked_at__isnull=True, device_type="rfid_terminal",
    ).first()


def owner_access(owner, action, also_clean, tag):
    if not owner.has_perm("core.view_makertag"):
        return False
    if (action == "clean" or also_clean) and not owner.has_perm("core.change_makertag"):
        return False
    if action == "remove" and not owner.has_perm("core.delete_makertag"):
        return False
    if tag is None or tag.owner_id != owner.pk or tag.status != "active":
        return False
    return True


def can_run(device, action, also_clean):
    key = device.api_key
    if not key or not key.is_active() or "tags:write" not in key.scopes:
        return False
    if (action == "clean" or also_clean) and CLEAN_CAPABILITY not in (device.capabilities or []):
        return False
    return True


def matches(item, tag):
    return bool(tag and tag.pk == item.tag_id_snapshot and
                tag.owner_id == item.owner_id and tag.status == "active" and
                tag.target_type == item.target_type and
                tag.target_id == item.target_id and
                tag.short_id == item.expected_short_id and
                tag.kind in ("nfc", "rfid") and
                MakerTag.normalise_code(tag.kind, tag.code) == item.expected_uid)


def cleanable(tag):
    return tag.kind == "nfc" and len(tag.code) == 14 and MakerTag.is_uid_like(tag.code)


def busy(device):
    now = timezone.now()
    if Operation.objects.filter(device=device, state="pending", expires_at__gt=now).exists():
        return True
    # A cleaned but not yet removed tag remains bound to this terminal.
    if Operation.objects.filter(device=device, state="cleaned", action="remove").exists():
        return True
    return (DeviceNdefWrite.objects.filter(device=device, state="pending", expires_at__gt=now).exists() or
            DeviceTagRegistration.objects.filter(device=device, state="pending", expires_at__gt=now).exists() or
            DeviceTagLookup.objects.filter(device=device, state="pending", expires_at__gt=now).exists())


def create(owner, device, tag, action, also_clean, source):
    return Operation.objects.create(
        owner=owner, device=device, tag=tag, tag_id_snapshot=tag.pk,
        expected_uid=MakerTag.normalise_code(tag.kind, tag.code),
        expected_short_id=tag.short_id, target_type=tag.target_type,
        target_id=tag.target_id, action=action, also_clean=also_clean,
        source=source, expires_at=timezone.now()+TTL,
    )


def validate(action, also_clean, tag, owner, device):
    if action not in ("clean", "remove") or not isinstance(also_clean, bool):
        return "Invalid operation."
    if action == "clean" and not also_clean:
        return "Cleaning requires physical NFC cleaning."
    if not owner_access(owner, action, also_clean, tag):
        return "Insufficient MakerTag permissions."
    if not can_run(device, action, also_clean):
        return "Terminal permissions/capabilities insufficient."
    if (action == "clean" or also_clean) and not cleanable(tag):
        return "Physical cleaning requires a registered 7-byte NTAG215-style NFC UID."
    if tag.kind not in ("nfc", "rfid"):
        return "Only physical MakerTags can be handled on the terminal."
    return None


@login_required
@require_http_methods(["POST"])
def begin(request):
    if not (request.is_secure() or settings.DEBUG):
        return failure("HTTPS required.", 403)
    try:
        data = json_payload(request, {"tag_id", "device_id", "action", "also_clean"})
        tag_id = uuid.UUID(str(data["tag_id"]))
        device_id = uuid.UUID(str(data["device_id"]))
    except (ValueError, TypeError, KeyError, json.JSONDecodeError):
        return failure("Invalid operation request.")
    with transaction.atomic():
        device = ConnectedDevice.objects.select_for_update(of=("self",)).select_related("api_key").filter(
            pk=device_id, owner=request.user, revoked_at__isnull=True, device_type="rfid_terminal"
        ).first()
        tag = MakerTag.objects.select_for_update().filter(pk=tag_id, owner=request.user).first()
        if not device or not tag:
            return failure("Paired terminal or MakerTag not found.", 404)
        err = validate(data["action"], data["also_clean"], tag, request.user, device)
        if err:
            return failure(err, 403)
        if busy(device):
            return failure("Terminal is handling another operation.", 409)
        item = create(request.user, device, tag, data["action"], data["also_clean"], "browser")
    return response(item, 201)


@require_http_methods(["POST"])
@require_device_scope("tags:write")
def device_begin(request):
    device = paired(request)
    if not device:
        return failure("Active paired terminal required.", 403)
    try:
        data = json_payload(request, {"uid", "action", "also_clean"})
        uid = MakerTag.normalise_code("nfc", data["uid"])
        if not MakerTag.is_uid_like(uid) or len(uid) not in (8, 14):
            return failure("Unsupported physical UID.")
    except (ValueError, TypeError, KeyError, json.JSONDecodeError):
        return failure("Invalid device operation request.")
    with transaction.atomic():
        device = ConnectedDevice.objects.select_for_update().get(pk=device.pk)
        tags = list(radio_tag_matches(
            MakerTag.objects.filter(owner=request.device_owner, status="active"),
            "nfc" if len(uid)==14 else "rfid", uid
        )[:2])
        if len(tags) != 1:
            return failure("No unique registered MakerTag found for UID.", 404 if not tags else 409)
        tag = MakerTag.objects.select_for_update().get(pk=tags[0].pk)
        err = validate(data["action"], data["also_clean"], tag, request.device_owner, device)
        if err:
            return failure(err, 403)
        if busy(device):
            return failure("Terminal is handling another operation.", 409)
        item = create(request.device_owner, device, tag, data["action"], data["also_clean"], "terminal")
    return response(item, 201)


@login_required
@require_http_methods(["GET"])
def status(request, operation_id):
    item = Operation.objects.select_related("tag").filter(pk=operation_id, owner=request.user).first()
    return response(item) if item else failure("Operation not found.", 404)


@login_required
@require_http_methods(["POST"])
def cancel(request, operation_id):
    if not (request.is_secure() or settings.DEBUG):
        return failure("HTTPS required.", 403)
    with transaction.atomic():
        item = Operation.objects.select_for_update().filter(pk=operation_id, owner=request.user).first()
        if not item:
            return failure("Operation not found.", 404)
        if item.state not in ("pending", "cleaned"):
            return failure("Operation cannot be cancelled.", 409)
        if item.state == "pending" and item.expires_at <= timezone.now():
            return failure("Operation expired.", 410)
        item.state = "cancelled"
        item.save(update_fields=["state", "updated_at"])
    return response(item)


@require_http_methods(["GET"])
@require_device_scope("tags:write")
def device_pending(request):
    device = paired(request)
    if not device:
        return failure("Active paired terminal required.", 403)
    # A verified wipe may have been reported just before an interrupted
    # removal. After reboot, let the *same terminal* recover that exact
    # operation without touching NFC memory or creating another session.
    item = Operation.objects.select_related("tag").filter(
        device=device, owner=request.device_owner, action="remove",
        state="cleaned"
    ).order_by("-created_at").first()
    if not item:
        item = Operation.objects.select_related("tag").filter(
            device=device, owner=request.device_owner, source="browser",
            state="pending", expires_at__gt=timezone.now()
        ).order_by("-created_at").first()
    result = JsonResponse({"operation": serialise(item) if item else None})
    result["Cache-Control"] = "no-store"
    return result


@require_http_methods(["GET"])
@require_device_scope("tags:write")
def device_status(request, operation_id):
    device = paired(request)
    item = Operation.objects.select_related("tag").filter(
        pk=operation_id, owner=request.device_owner, device=device
    ).first() if device else None
    if not item:
        return failure("Operation not found.", 404)
    status = serialise(item)
    if status["state"] in ("pending", "cleaned") and (
        not matches(item, item.tag) or
        not owner_access(request.device_owner, item.action, item.also_clean, item.tag) or
        not can_run(device, item.action, item.also_clean)
    ):
        status["state"] = "invalid"
    result = JsonResponse({"operation": status})
    result["Cache-Control"] = "no-store"
    return result


@require_http_methods(["POST"])
@require_device_scope("tags:write")
def device_cancel(request, operation_id):
    device = paired(request)
    if not device:
        return failure("Active paired terminal required.", 403)
    with transaction.atomic():
        item = Operation.objects.select_for_update().filter(
            pk=operation_id, owner=request.device_owner, device=device
        ).first()
        if not item:
            return failure("Operation not found.", 404)
        if item.state not in ("pending", "cleaned"):
            return failure("Operation cannot be cancelled.", 409)
        item.state = "cancelled"
        item.save(update_fields=["state", "updated_at"])
    return response(item)


@require_http_methods(["POST"])
@require_device_scope("tags:write")
def device_cleaned(request, operation_id):
    """Only terminal-reported *verified* blank memory may advance this phase."""
    device = paired(request)
    if not device:
        return failure("Active paired terminal required.", 403)
    try:
        data = json_payload(request, {"uid", "verified_empty"})
        if data["verified_empty"] is not True:
            return failure("Full empty-user-data readback required.", 409)
        uid = MakerTag.normalise_code("nfc", data["uid"])
    except (ValueError, TypeError, KeyError, json.JSONDecodeError):
        return failure("Invalid verification.")
    with transaction.atomic():
        item = Operation.objects.select_for_update(of=("self",)).select_related("tag").filter(
            pk=operation_id, owner=request.device_owner, device=device
        ).first()
        if not item:
            return failure("Operation not found.", 404)
        if item.state in ("cleaned", "completed") and item.cleaned_at and uid == item.expected_uid:
            return response(item)
        if item.state != "pending" or item.expires_at <= timezone.now():
            return failure("Operation cancelled or expired.", 410)
        if not (item.action == "clean" or item.also_clean) or uid != item.expected_uid:
            return failure("Wrong UID or operation.", 409)
        if not matches(item, item.tag) or not owner_access(request.device_owner, item.action, item.also_clean, item.tag):
            return failure("MakerTag registration changed.", 409)
        if not can_run(device, item.action, item.also_clean):
            return failure("Device permission revoked.", 403)
        now = timezone.now()
        item.cleaned_at = now
        item.state = "completed" if item.action == "clean" else "cleaned"
        if item.action == "clean":
            item.completed_at = now
        item.save(update_fields=["cleaned_at", "state", "completed_at", "updated_at"])
        _record_tag_event(item.tag, request.device_owner, "updated",
                          "Physical NFC user data cleared and verified by paired terminal.",
                          {"device_id": str(device.pk), "operation_id": str(item.pk)})
    return response(item)


@require_http_methods(["POST"])
@require_device_scope("tags:write")
def device_remove(request, operation_id):
    """Delete the exact registered MakerTag, never its inventory record."""
    device = paired(request)
    if not device:
        return failure("Active paired terminal required.", 403)
    try:
        data = json_payload(request, {"uid"})
        uid = MakerTag.normalise_code("nfc", data["uid"])
    except (ValueError, TypeError, KeyError, json.JSONDecodeError):
        return failure("Invalid removal request.")
    with transaction.atomic():
        item = Operation.objects.select_for_update(of=("self",)).select_related("tag").filter(
            pk=operation_id, owner=request.device_owner, device=device
        ).first()
        if not item:
            return failure("Operation not found.", 404)
        if item.state == "completed" and item.action == "remove" and uid == item.expected_uid:
            return response(item)
        if item.action != "remove" or uid != item.expected_uid:
            return failure("Wrong UID or operation.", 409)
        if item.also_clean:
            if item.state != "cleaned" or not item.cleaned_at:
                return failure("Physical NFC cleaning has not been verified.", 409)
        elif item.state != "pending" or item.expires_at <= timezone.now():
            return failure("Operation cancelled or expired.", 410)
        if not matches(item, item.tag):
            return failure("MakerTag registration changed.", 409)
        if not owner_access(request.device_owner, "remove", item.also_clean, item.tag) or not can_run(device, "remove", item.also_clean):
            return failure("Removal authorization revoked.", 403)
        # Lock and revalidate the actual tag, preventing reassignment races.
        tag = MakerTag.objects.select_for_update().filter(pk=item.tag_id_snapshot).first()
        if not matches(item, tag):
            return failure("MakerTag registration changed.", 409)
        item.tag = None
        item.state = "completed"
        item.completed_at = timezone.now()
        item.save(update_fields=["tag", "state", "completed_at", "updated_at"])
        tag.delete()  # Existing semantics: no inventory or spool UID deletion.
    return response(item)
