"""Short-lived, owner-bound NFC write requests for paired RFID terminals.

The server authorizes an exact URL, permanent short ID and physical UID.
The firmware MUST independently inspect NTAG215 memory, obtain physical
confirmation, write, and read back before reporting verified completion.
"""
import json
import uuid
from datetime import timedelta

from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.db import transaction
from django.http import JsonResponse
from django.utils import timezone
from django.views.decorators.http import require_http_methods

from .device_api_views import require_device_scope
from .maker_tags import TARGETS, resolve_tag_target
from .models import ConnectedDevice, DeviceNdefWrite, MakerTag
from .tag_ndef import _base_origin

TTL = timedelta(minutes=5)
CAPABILITY = "ntag215_ndef_write"


def error(message, code=400):
    response = JsonResponse({"error": message}, status=code)
    response["Cache-Control"] = "no-store"
    return response


def read_payload(request, fields):
    if len(request.body) > 1024:
        raise ValueError("Request too large.")
    data = json.loads(request.body)
    if not isinstance(data, dict) or set(data) != fields:
        raise ValueError("Unexpected request fields.")
    return data


def present(item):
    state = "expired" if item.state == "pending" and item.expires_at <= timezone.now() else item.state
    return {"id": str(item.pk), "state": state, "device_id": str(item.device_id),
            "maker_tag_id": f"MV-{item.tag.short_id}", "uid": item.expected_uid,
            "url": item.url, "expires_at": item.expires_at.isoformat()}


def paired(request):
    return ConnectedDevice.objects.filter(
        owner=request.device_owner, api_key=request.device_key,
        revoked_at__isnull=True, device_type="rfid_terminal",
    ).first()


@login_required
@require_http_methods(["POST"])
def begin(request):
    if not (request.is_secure() or settings.DEBUG):
        return error("HTTPS required.", 403)
    if not request.user.has_perm("core.change_makertag"):
        return error("Insufficient permissions.", 403)
    try:
        data = read_payload(request, {"tag_id", "device_id", "origin", "override"})
        tag_id, device_id = uuid.UUID(str(data["tag_id"])), uuid.UUID(str(data["device_id"]))
        source, _, _ = _base_origin(data["origin"])
        header, _, _ = _base_origin(request.headers.get("Origin", ""))
        if header != source:
            return error("Browser origin mismatch.")
        chosen, _, _ = _base_origin(data["override"] or source)
    except (ValueError, TypeError, KeyError, json.JSONDecodeError) as exc:
        return error(str(exc) or "Invalid request.")
    with transaction.atomic():
        device = ConnectedDevice.objects.select_for_update(of=("self",)).select_related("api_key").filter(
            pk=device_id, owner=request.user, device_type="rfid_terminal",
            revoked_at__isnull=True,
        ).first()
        if not device or not device.api_key or not device.api_key.is_active():
            return error("Active paired RFID terminal not found.", 404)
        if "tags:write" not in device.api_key.scopes or CAPABILITY not in device.capabilities:
            return error("Terminal does not advertise NFC-writing capability.", 403)
        tag = MakerTag.objects.select_for_update().filter(
            pk=tag_id, owner=request.user, status="active", kind="nfc"
        ).first()
        if not tag or not MakerTag.is_uid_like(tag.code) or len(tag.code) != 14:
            return error("A registered NTAG215-style seven-byte UID is required.", 400)
        definition = TARGETS.get(tag.target_type)
        if not definition or not request.user.has_perm(f"core.view_{definition.model._meta.model_name}"):
            return error("Tag target not accessible.", 404)
        try:
            resolve_tag_target(request.user, tag.target_type, tag.target_id)
        except ValidationError:
            return error("Tag target not accessible.", 404)
        url = f"{chosen}/t/MV-{tag.short_id}/"
        if len(url.encode("utf-8")) > 240:
            return error("URL too long.")
        if DeviceNdefWrite.objects.filter(
            device=device, state="pending", expires_at__gt=timezone.now()
        ).exists():
            return error("Terminal already has a pending NFC write.", 409)
        # Prevent overlapping writes and registrations sharing the same reader.
        from .models import DeviceTagRegistration, DeviceTagLookup
        for model in (DeviceTagRegistration, DeviceTagLookup):
            if model.objects.filter(device=device, state="pending", expires_at__gt=timezone.now()).exists():
                return error("Terminal is already handling another operation.", 409)
        item = DeviceNdefWrite.objects.create(
            owner=request.user, device=device, tag=tag, url=url,
            expected_uid=MakerTag.normalise_code("nfc", tag.code),
            expires_at=timezone.now() + TTL,
        )
    response = JsonResponse(present(item), status=201)
    response["Cache-Control"] = "no-store"
    return response


@login_required
@require_http_methods(["GET"])
def status(request, write_id):
    item = DeviceNdefWrite.objects.select_related("tag").filter(
        pk=write_id, owner=request.user).first()
    if not item:
        return error("NFC write request not found.", 404)
    response = JsonResponse(present(item))
    response["Cache-Control"] = "no-store"
    return response


@login_required
@require_http_methods(["POST"])
def cancel(request, write_id):
    if not (request.is_secure() or settings.DEBUG):
        return error("HTTPS required.", 403)
    with transaction.atomic():
        item = DeviceNdefWrite.objects.select_for_update().select_related("tag").filter(
            pk=write_id, owner=request.user
        ).first()
        if not item:
            return error("NFC write request not found.", 404)
        if item.state != "pending" or item.expires_at <= timezone.now():
            return error("NFC write is no longer pending.", 409)
        item.state = "cancelled"
        item.save(update_fields=["state", "updated_at"])
    return JsonResponse(present(item))


@require_http_methods(["GET"])
@require_device_scope("tags:write")
def device_pending(request):
    device = paired(request)
    if not device:
        return error("Active paired terminal required.", 403)
    item = DeviceNdefWrite.objects.select_related("tag").filter(
        device=device, owner=request.device_owner, state="pending",
        expires_at__gt=timezone.now()
    ).order_by("-created_at").first()
    response = JsonResponse({"request": present(item) if item else None})
    response["Cache-Control"] = "no-store"
    return response


@require_http_methods(["GET"])
@require_device_scope("tags:write")
def device_status(request, write_id):
    """Terminal must recheck cancellation/expiry immediately before any write."""
    device = paired(request)
    if not device:
        return error("Active paired terminal required.", 403)
    item = DeviceNdefWrite.objects.select_related("tag").filter(
        pk=write_id, owner=request.device_owner, device=device
    ).first()
    if not item:
        return error("NFC write request not found.", 404)
    # A changed/retired tag or changed UID invalidates the queued operation.
    response = present(item)
    if response["state"] == "pending" and (
        item.tag.status != "active" or item.tag.owner_id != request.device_owner.pk or
        item.tag.kind != "nfc" or
        MakerTag.normalise_code("nfc", item.tag.code) != item.expected_uid
    ):
        response["state"] = "invalid"
    result = JsonResponse(response)
    result["Cache-Control"] = "no-store"
    return result


@require_http_methods(["POST"])
@require_device_scope("tags:write")
def device_cancel(request, write_id):
    """Physical Back button cancels the same bounded operation as the browser."""
    device = paired(request)
    if not device:
        return error("Active paired terminal required.", 403)
    with transaction.atomic():
        item = DeviceNdefWrite.objects.select_for_update(of=("self",)).select_related("tag").filter(
            pk=write_id, owner=request.device_owner, device=device
        ).first()
        if not item:
            return error("NFC write request not found.", 404)
        if item.state != "pending" or item.expires_at <= timezone.now():
            return error("NFC write is no longer pending.", 409)
        item.state = "cancelled"
        item.save(update_fields=["state", "updated_at"])
    return JsonResponse(present(item))


@require_http_methods(["POST"])
@require_device_scope("tags:write")
def device_complete(request, write_id):
    device = paired(request)
    if not device:
        return error("Active paired terminal required.", 403)
    try:
        data = read_payload(request, {"uid", "verified_url"})
        uid = MakerTag.normalise_code("nfc", data["uid"])
        verified_url = data["verified_url"]
        if not isinstance(verified_url, str):
            return error("Invalid verification.")
    except (ValueError, TypeError, KeyError, json.JSONDecodeError):
        return error("Invalid verification.")
    with transaction.atomic():
        item = DeviceNdefWrite.objects.select_for_update().select_related("tag").filter(
            pk=write_id, device=device, owner=request.device_owner
        ).first()
        if not item:
            return error("NFC write request not found.", 404)
        if item.state == "completed":
            if uid == item.expected_uid and verified_url == item.url:
                return JsonResponse(present(item))
            return error("Request already completed with different data.", 409)
        if item.state != "pending" or item.expires_at <= timezone.now():
            return error("Request cancelled or expired.", 410)
        if item.tag.owner_id != request.device_owner.pk or item.tag.status != "active" or item.tag.kind != "nfc":
            return error("MakerTag changed or retired.", 409)
        if MakerTag.normalise_code("nfc", item.tag.code) != item.expected_uid:
            return error("Physical tag identity changed.", 409)
        if uid != item.expected_uid or verified_url != item.url:
            return error("Physical UID or read-back URL mismatch.", 409)
        item.state = "completed"
        item.completed_at = timezone.now()
        item.save(update_fields=["state", "completed_at", "updated_at"])
    return JsonResponse(present(item))
