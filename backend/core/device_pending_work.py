"""One authenticated, owner/device-scoped terminal idle-work snapshot.

This replaces four separate idle TLS polls; individual workflows continue to
own their existing confirmation, authorisation, cancellation and completion APIs.
A snapshot is discovery only and never authorises physical NFC writes.
"""
from django.http import JsonResponse
from django.utils import timezone
from django.views.decorators.http import require_http_methods

from .device_api_views import require_device_scope
from .device_tag_registration import summary
from .device_ndef_write import present
from .device_makertag_operations import serialise
from .models import (ConnectedDevice, DeviceTagRegistration, DeviceTagLookup,
                     DeviceNdefWrite)
from .device_tag_operations_model import DeviceMakerTagOperation


@require_http_methods(["GET"])
@require_device_scope("tags:read")
def pending_work(request):
    device = ConnectedDevice.objects.filter(
        owner=request.device_owner, api_key=request.device_key,
        revoked_at__isnull=True, device_type="rfid_terminal",
    ).first()
    if device is None:
        return JsonResponse({"error": "Active paired terminal required."}, status=403)
    now = timezone.now()
    scopes = request.device_key.scopes or []
    can_write = "tags:write" in scopes
    response = {"registration": None, "ndef_write": None,
                "lookup": None, "operation": None}
    if request.device_owner.has_perm("core.view_makertag"):
        lookup = DeviceTagLookup.objects.filter(
            device=device, owner=request.device_owner, state="pending",
            expires_at__gt=now
        ).order_by("-created_at").first()
        if lookup is not None:
            response["lookup"] = {"id": str(lookup.pk)}
    if can_write:
        reg = DeviceTagRegistration.objects.select_related(
            "owner", "tag", "ndef_write"
        ).filter(device=device, owner=request.device_owner, state="pending",
                 expires_at__gt=now).order_by("-created_at").first()
        if reg is not None:
            response["registration"] = summary(reg)
        write = DeviceNdefWrite.objects.select_related("tag").filter(
            device=device, owner=request.device_owner, state="pending",
            expires_at__gt=now
        ).order_by("-created_at").first()
        if write is not None and request.device_owner.has_perm("core.change_makertag"):
            response["ndef_write"] = present(write)
        # Recover a two-phase clean/remove after a reboot without re-erasing
        # the tag, retaining the already-bound operation ID.
        op = DeviceMakerTagOperation.objects.select_related(
            "owner", "tag", "device"
        ).filter(device=device, owner=request.device_owner,
                 state="cleaned", action="remove").order_by("-created_at").first()
        if op is None:
            op = DeviceMakerTagOperation.objects.select_related(
                "owner", "tag", "device"
            ).filter(device=device, owner=request.device_owner,
                     state="pending", expires_at__gt=now).order_by("-created_at").first()
        if op is not None:
            if (op.action != "remove" or request.device_owner.has_perm("core.delete_makertag")) and (
                not op.also_clean or request.device_owner.has_perm("core.change_makertag")
            ):
                response["operation"] = serialise(op)
    result = JsonResponse(response)
    result["Cache-Control"] = "no-store"
    return result
