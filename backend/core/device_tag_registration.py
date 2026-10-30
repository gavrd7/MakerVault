"""Secure browser-to-paired-terminal Maker Tag registration workflow."""
import json
import uuid
from datetime import timedelta

from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.core import signing
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.http import JsonResponse
from django.utils import timezone
from django.views.decorators.http import require_http_methods

from .device_api_views import require_device_scope, _scan_payload, _tag_summary
from .models import ConnectedDevice, DeviceTagRegistration, DeviceNdefWrite, MakerTag
from .tag_ndef import _base_origin
from .maker_tags import TARGETS, resolve_tag_target, serialise_tag_target
from .api_views import _sync_rfid_tag_to_spool, _record_tag_event
from .radio_tag_identity import radio_tag_matches

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
            "tag": _tag_summary(item.tag, item.owner) if item.tag_id and item.tag else None,
            "tag_kind": item.tag.kind if item.tag_id and item.tag else "",
            "ndef_write": {"id": str(item.ndef_write.pk), "state": "expired" if item.ndef_write.state == "pending" and item.ndef_write.expires_at <= timezone.now() else item.ndef_write.state, "url": item.ndef_write.url} if item.ndef_write_id and item.ndef_write else None,
            "ndef_write_id": str(item.ndef_write_id) if item.ndef_write_id else "",
            "ndef_url": item.ndef_write.url if item.ndef_write_id and item.ndef_write else "",
            "ndef_tag_id": f"MV-{item.tag.short_id}" if item.ndef_write_id and item.tag_id else ""}


@login_required
@require_http_methods(["POST"])
def begin(request):
    if not secure(request):
        return failure("HTTPS required.", 403)
    try:
        data = payload(request)
        basic = {"device_id", "target_type", "target_id"}
        extended = basic | {"origin", "override"}
        if set(data) not in (basic, extended):
            raise ValueError("Provide valid device, target and optional NFC address.")
        chosen_origin = ""
        if set(data) == extended:
            source, _, _ = _base_origin(data["origin"])
            header, _, _ = _base_origin(request.headers.get("Origin", ""))
            if source != header:
                raise ValueError("Browser origin mismatch.")
            chosen_origin, _, _ = _base_origin(data["override"] or source)
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
        device = ConnectedDevice.objects.select_for_update(of=("self",)).select_related("api_key").filter(
            pk=device_id, owner=request.user, device_type="rfid_terminal", revoked_at__isnull=True
        ).first()
        if not device or not device.api_key or not device.api_key.is_active():
            return failure("Active paired RFID terminal not found.", 404)
        if "tags:write" not in device.api_key.scopes:
            return failure("The selected device requires tags:write permission.", 403)
        if chosen_origin and ("ntag215_ndef_write" not in (device.capabilities or []) or
                              not request.user.has_perm("core.change_makertag")):
            return failure("This terminal or account cannot complete NFC programming.", 403)
        if DeviceTagRegistration.objects.filter(
            device=device, state="pending", expires_at__gt=timezone.now()
        ).exists():
            return failure("The terminal already has a pending registration.", 409)
        item = DeviceTagRegistration.objects.create(
            owner=request.user, device=device, target_type=kind,
            target_id=target.pk, ndef_origin=chosen_origin,
            expires_at=timezone.now() + TTL
        )
    return JsonResponse(summary(item), status=201)


@login_required
@require_http_methods(["GET"])
def status(request, registration_id):
    item = DeviceTagRegistration.objects.select_related("tag", "ndef_write").filter(
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



@login_required
@require_http_methods(["GET"])
def browser_pending(request):
    try:
        device_id = uuid.UUID(request.GET.get("device_id", ""))
    except (ValueError, TypeError):
        return failure("Invalid terminal.")
    device = ConnectedDevice.objects.filter(pk=device_id, owner=request.user, device_type="rfid_terminal", revoked_at__isnull=True).first()
    if not device:
        return failure("Terminal not found.", 404)
    item = DeviceTagRegistration.objects.select_related("tag").filter(
        owner=request.user, device=device, state="pending", expires_at__gt=timezone.now()
    ).order_by("-created_at").first()
    response = JsonResponse({"registration": summary(item) if item else None})
    response["Cache-Control"] = "no-store"
    return response



@require_http_methods(["GET"])
@require_device_scope("tags:write")
def device_status(request, registration_id):
    device = paired_device(request)
    if not device:
        return failure("Active paired RFID terminal required.", 403)
    item = DeviceTagRegistration.objects.select_related("tag").filter(
        pk=registration_id, device=device, owner=request.device_owner
    ).first()
    if not item:
        return failure("Registration not found.", 404)
    response = JsonResponse({"id": str(item.pk),
                            "state": "expired" if item.state == "pending" and item.expires_at <= timezone.now() else item.state})
    response["Cache-Control"] = "no-store"
    return response


@require_http_methods(["POST"])
@require_device_scope("tags:write")
def device_cancel(request, registration_id):
    device = paired_device(request)
    if not device:
        return failure("Active paired RFID terminal required.", 403)
    with transaction.atomic():
        item = DeviceTagRegistration.objects.select_for_update().filter(
            pk=registration_id, device=device, owner=request.device_owner
        ).first()
        if not item:
            return failure("Registration not found.", 404)
        if item.state != "pending" or item.expires_at <= timezone.now():
            return failure("Registration is no longer pending.", 409)
        item.state = "cancelled"
        item.save(update_fields=["state", "updated_at"])
    return JsonResponse(summary(item))


def attach_ndef_write(item, device, tag):
    """Queue one authorised NDEF operation during confirmed assignment."""
    if not item.ndef_origin or tag.kind != "nfc" or len(tag.code) != 14:
        return
    if "ntag215_ndef_write" not in (device.capabilities or []):
        return
    url = f"{item.ndef_origin}/t/MV-{tag.short_id}/"
    if len(url.encode("utf-8")) > 240:
        return
    if DeviceNdefWrite.objects.filter(
        device=device, state="pending", expires_at__gt=timezone.now()
    ).exists():
        return
    item.ndef_write = DeviceNdefWrite.objects.create(
        owner=item.owner, device=device, tag=tag, url=url,
        expected_uid=MakerTag.normalise_code("nfc", tag.code),
        expires_at=timezone.now() + TTL,
    )


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
def device_probe(request, registration_id):
    """Read-only preflight: show any existing assignment before physical confirmation."""
    device = paired_device(request)
    if not device:
        return failure("Active paired terminal required.", 403)
    try:
        data = _scan_payload(request, fields={"kind", "uid"})
    except OverflowError:
        return failure("Request too large.", 413)
    except (ValueError, TypeError):
        return failure("Invalid scanned tag.")
    item = DeviceTagRegistration.objects.filter(
        pk=registration_id, device=device, owner=request.device_owner,
        state="pending", expires_at__gt=timezone.now()
    ).first()
    if not item:
        return failure("Registration not pending.", 410)
    target = resolve_tag_target(request.device_owner, item.target_type, item.target_id)
    existing = radio_tag_matches(MakerTag.objects.all(), data["kind"], data["uid"]).first()
    if not existing:
        return JsonResponse({"reassign_required": False, "already_assigned": False})
    if existing.owner_id != request.device_owner.pk:
        return failure("This tag cannot be reassigned.", 409)
    if existing.target_type == item.target_type and existing.target_id == target.pk:
        return JsonResponse({"reassign_required": False, "already_assigned": True})
    if not request.device_owner.has_perm("core.change_makertag"):
        return failure("Reassignment requires edit permission.", 403)
    binding = [str(item.pk), str(device.pk), str(existing.pk), data["uid"],
               item.target_type, str(target.pk)]
    token = signing.dumps(binding, salt="makervault-terminal-reassign")
    old = serialise_tag_target(request.device_owner, existing.target_type, existing.target_id) or {}
    response = JsonResponse({"reassign_required": True, "reassign_token": token,
                             "current_label": old.get("label", "Existing record")})
    response["Cache-Control"] = "no-store"
    return response


@require_http_methods(["POST"])
@require_device_scope("tags:write")
def device_complete(request, registration_id):
    device = paired_device(request)
    if not device:
        return failure("Active paired RFID terminal required.", 403)
    if not request.device_owner.has_perm("core.add_makertag"):
        return failure("Insufficient tag permissions.", 403)
    try:
        raw = json.loads(request.body)
        confirm = raw.get("reassign_token") if isinstance(raw, dict) else None
        data = _scan_payload(request, fields={"kind", "uid", "reassign_token"} if confirm is not None else {"kind", "uid"})
        if confirm is not None and (not isinstance(confirm, str) or len(confirm) > 1024):
            raise ValueError("Invalid reassignment confirmation.")
    except OverflowError:
        return failure("Request too large.", 413)
    except (ValueError, TypeError):
        return failure("Invalid scanned tag.")
    with transaction.atomic():
        item = DeviceTagRegistration.objects.select_for_update(of=("self",)).select_related("tag").filter(
            pk=registration_id, device=device, owner=request.device_owner
        ).first()
        if not item:
            return failure("Registration not found.", 404)
        if item.state == "completed":
            if item.tag and item.tag.kind in ("nfc", "rfid") and data["kind"] in ("nfc", "rfid") and item.tag.code == data["uid"]:
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
            # Savepoint keeps a failed tag insert from poisoning the enclosing
            # transaction (including on PostgreSQL unique constraint errors).
            with transaction.atomic():
                target = resolve_tag_target(request.device_owner, item.target_type, item.target_id)
                existing = radio_tag_matches(MakerTag.objects.select_for_update(), data["kind"], data["uid"]).first()
                if existing:
                    if existing.owner_id != request.device_owner.pk:
                        return failure("This tag cannot be reassigned.", 409)
                    if existing.target_type == item.target_type and existing.target_id == target.pk:
                        tag = existing
                        item.tag = tag
                        item.state = "completed"
                        item.completed_at = timezone.now()
                        attach_ndef_write(item, device, tag)
                        item.save(update_fields=["tag", "state", "completed_at", "ndef_write", "updated_at"])
                        return JsonResponse(summary(item), status=200)
                    if not request.device_owner.has_perm("core.change_makertag"):
                        return failure("Tag reassignment requires edit permission.", 403)
                    binding = [str(item.pk), str(device.pk), str(existing.pk), data["uid"],
                               item.target_type, str(target.pk)]
                    if confirm is None:
                        token = signing.dumps(binding, salt="makervault-terminal-reassign")
                        response = JsonResponse({
                            "error": "Already registered. Reassign this tag?",
                            "reassign_required": True, "reassign_token": token,
                            "current_label": serialise_tag_target(
                                request.device_owner, existing.target_type, existing.target_id
                            ).get("label", "Existing record"),
                        }, status=409)
                        response["Cache-Control"] = "no-store"
                        return response
                    try:
                        confirmed = signing.loads(confirm, salt="makervault-terminal-reassign", max_age=90)
                    except signing.BadSignature:
                        return failure("Reassignment confirmation expired or invalid.", 409)
                    if confirmed != binding:
                        return failure("Reassignment confirmation does not match this tag.", 409)
                    previous = {"kind": existing.kind, "code": existing.code,
                                "target_type": existing.target_type, "target_id": str(existing.target_id)}
                    old_view = serialise_tag_target(request.device_owner, existing.target_type, existing.target_id) or {}
                    new_view = serialise_tag_target(request.device_owner, item.target_type, target.pk) or {}
                    def label_snapshot(info):
                        name, code = info.get("label", ""), info.get("record_code", "")
                        return f"{name} ({code})" if code else name
                    previous_label = label_snapshot(old_view)
                    new_label = label_snapshot(new_view)
                    existing.target_type = item.target_type
                    existing.target_id = target.pk
                    existing.full_clean()
                    existing.save()
                    _sync_rfid_tag_to_spool(existing, previous=previous)
                    _record_tag_event(existing, request.device_owner, "reassigned",
                                      "Reassigned from a paired RFID terminal.", {
                                          "previous": previous, "previous_label": previous_label,
                                          "new_label": new_label, "new_target_type": item.target_type,
                                          "new_target_id": str(target.pk),
                                          "device_id": str(device.pk), "request_id": str(item.pk)
                                      })
                    tag = existing
                elif confirm is not None:
                    return failure("The previously scanned tag is no longer registered.", 409)
                else:
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
        attach_ndef_write(item, device, tag)
        item.save(update_fields=["tag", "state", "completed_at", "ndef_write", "updated_at"])
    return JsonResponse(summary(item), status=201)
