"""Browser-approved, one-time device pairing. Device claims are NOT bearer API keys."""
import hashlib
import hmac
import json
import re
import secrets
from datetime import timedelta

from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.http import JsonResponse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

from .device_api_keys import generate_token, validate_scopes
from .device_rate_limit import allowance
from .models import ConnectedDevice, DevicePairing, UserApiKey
from .device_api_views import require_device_scope

PAIRING_TTL = timedelta(minutes=5)
DEVICE_SCOPES = {"rfid_terminal": {"tags:read", "tags:write", "inventory:read", "devices:status"},
                 "filament_scale": {"tags:read", "inventory:read", "spools:weight", "devices:status"}}


def error(message, status=400):
    response = JsonResponse({"error": message}, status=status)
    response["Cache-Control"] = "no-store"
    return response


def payload(request):
    if len(request.body) > 2048:
        raise ValueError("Request too large.")
    data = json.loads(request.body or b"{}")
    if not isinstance(data, dict):
        raise ValueError("Expected an object.")
    return data


def secure(request):
    # TLS terminates at the configured trusted reverse proxy in production.
    from django.conf import settings
    return request.is_secure() or settings.DEBUG


def limited(request, group, identity, maximum):
    allowed, retry = allowance(group, identity, limit=maximum)
    if allowed is None:
        return error("Pairing rate limiter unavailable.", 503)
    if not allowed:
        response = error("Pairing requests temporarily limited.", 429)
        response["Retry-After"] = str(retry)
        return response
    return None


def describe(device):
    return {"id": str(device.id), "name": device.name, "device_uid": device.device_uid,
            "device_type": device.device_type, "firmware_version": device.firmware_version,
            "capabilities": device.capabilities, "reported_status": device.reported_status, "scopes": device.api_key.scopes if device.api_key else [],
            "last_seen_at": device.last_seen_at.isoformat() if device.last_seen_at else None,
            "revoked_at": device.revoked_at.isoformat() if device.revoked_at else None,
            "online": bool(device.last_seen_at and device.last_seen_at > timezone.now() - timedelta(minutes=3)
                           and not device.revoked_at)}


@csrf_exempt
@require_http_methods(["POST"])
def start_pairing(request):
    """Unconfigured device submits its own random proof; code must be shown on its display."""
    if not secure(request):
        return error("HTTPS required.", 403)
    throttle = limited(request, "pair-start", request.META.get("REMOTE_ADDR", "unknown"), 10)
    if throttle:
        return throttle
    try:
        data = payload(request)
        uid, kind, proof = data.get("device_uid"), data.get("device_type"), data.get("claim_secret")
        if not isinstance(uid, str) or not re.fullmatch(r"[A-Za-z0-9._:-]{8,120}", uid):
            raise ValueError("Invalid device identifier.")
        if kind not in DEVICE_SCOPES:
            raise ValueError("Unsupported device type.")
        if not isinstance(proof, str) or not re.fullmatch(r"[A-Za-z0-9_-]{43,128}", proof):
            raise ValueError("Device must generate a strong random claim secret.")
    except (ValueError, TypeError, json.JSONDecodeError) as exc:
        return error(str(exc))
    if ConnectedDevice.objects.filter(device_uid=uid, revoked_at__isnull=True).exists():
        return error("This device identity is already registered.", 409)
    # Expired unclaimed rows do not block new setup; claim IDs are never reused.
    with transaction.atomic():
        DevicePairing.objects.filter(device_uid=uid, approved_by__isnull=True).delete()
        for _ in range(8):
            code = str(secrets.randbelow(100000000)).zfill(8)
            if not DevicePairing.objects.filter(confirmation_code=code).exists():
                break
        else:
            return error("Unable to generate a unique confirmation code.", 503)
        claim = DevicePairing.objects.create(
            device_uid=uid, device_type=kind,
            claim_digest=hashlib.sha256(proof.encode("ascii")).hexdigest(),
            confirmation_code=code, expires_at=timezone.now() + PAIRING_TTL,
        )
    result = JsonResponse({"pairing_id": str(claim.id), "confirmation_code": code,
                           "expires_at": claim.expires_at.isoformat()}, status=201)
    result["Cache-Control"] = "no-store"
    return result


@login_required
@require_http_methods(["GET", "POST"])
def connected_devices(request):
    if request.method == "GET":
        items = ConnectedDevice.objects.filter(owner=request.user).select_related("api_key")[:250]
        return JsonResponse({"rows": [describe(item) for item in items],
                             "device_types": list(DEVICE_SCOPES)})
    return error("Use the pairing approval endpoint to register devices.", 405)


@login_required
@require_http_methods(["POST"])
def approve_pairing(request):
    if not secure(request):
        return error("HTTPS required.", 403)
    throttle = limited(request, "pair-approve", str(request.user.pk), 10)
    if throttle:
        return throttle
    try:
        data = payload(request)
        code, name = data.get("confirmation_code"), data.get("name")
        requested_type = data.get("device_type")
        if requested_type not in DEVICE_SCOPES:
            raise ValueError("Select a supported device type.")
        if not isinstance(code, str) or not re.fullmatch(r"[0-9]{8}", code):
            raise ValueError("Enter the eight-digit code shown on the device.")
        if not isinstance(name, str) or not 1 <= len(name.strip()) <= 120:
            raise ValueError("Give the device a name.")
    except (ValueError, TypeError, json.JSONDecodeError) as exc:
        return error(str(exc))
    with transaction.atomic():
        claim = DevicePairing.objects.select_for_update().filter(confirmation_code=code).first()
        if not claim or claim.expires_at <= timezone.now() or claim.consumed_at:
            return error("Pairing code is invalid, expired or already used.", 404)
        if claim.approved_by_id:
            return error("Device awaiting completion.", 409)
        if claim.device_type != requested_type:
            return error("Pairing code belongs to a different device type.", 409)
        existing = ConnectedDevice.objects.filter(device_uid=claim.device_uid).first()
        if existing and (existing.revoked_at is None or existing.owner_id != request.user.pk):
            return error("Device identity is already owned.", 409)
        allowed = DEVICE_SCOPES[claim.device_type]
        scopes = data.get("scopes", ["tags:read", "devices:status"])
        try:
            scopes = list(validate_scopes(scopes))
        except ValueError as exc:
            return error(str(exc))
        if not set(scopes) <= allowed:
            return error("Unsupported scope for this device type.")
        claim.approved_by = request.user
        claim.approved_name = name.strip()
        claim.approved_scopes = scopes
        claim.save(update_fields=["approved_by", "approved_name", "approved_scopes", "updated_at"])
    return JsonResponse({"approved": True, "device_type": claim.device_type,
                         "pairing_id": str(claim.pk), "device_uid": claim.device_uid})


@csrf_exempt
@require_http_methods(["POST"])
def complete_pairing(request, pairing_id):
    """Deliver the credential once to the device proving possession of its private claim secret."""
    if not secure(request):
        return error("HTTPS required.", 403)
    throttle = limited(request, "pair-complete", request.META.get("REMOTE_ADDR", "unknown"), 30)
    if throttle:
        return throttle
    try:
        proof = payload(request).get("claim_secret")
        if not isinstance(proof, str) or len(proof) > 128:
            raise ValueError("Invalid claim proof.")
    except (ValueError, TypeError, json.JSONDecodeError) as exc:
        return error(str(exc))
    with transaction.atomic():
        claim = DevicePairing.objects.select_for_update().filter(pk=pairing_id).first()
        if not claim or claim.expires_at <= timezone.now() or claim.consumed_at:
            return error("Pairing session expired or already completed.", 410)
        digest = hashlib.sha256(proof.encode("utf-8")).hexdigest()
        if not hmac.compare_digest(digest, claim.claim_digest):
            return error("Invalid claim proof.", 401)
        if not claim.approved_by_id or not claim.approved_by.is_active:
            return JsonResponse({"status": "pending"}, status=202)
        existing = ConnectedDevice.objects.select_for_update().filter(device_uid=claim.device_uid).first()
        if existing and (existing.revoked_at is None or existing.owner_id != claim.approved_by_id):
            return error("Device identity is already owned.", 409)
        issued = generate_token()
        key = UserApiKey.objects.create(
            owner=claim.approved_by, name=claim.approved_name,
            identifier=issued.identifier, secret_digest=issued.digest, scopes=claim.approved_scopes,
        )
        if existing:
            existing.name = claim.approved_name
            existing.device_type = claim.device_type
            existing.api_key = key
            existing.revoked_at = None
            existing.last_seen_at = None
            existing.save(update_fields=["name", "device_type", "api_key", "revoked_at", "last_seen_at", "updated_at"])
            device = existing
        else:
            device = ConnectedDevice.objects.create(
                owner=claim.approved_by, device_uid=claim.device_uid,
                device_type=claim.device_type, name=claim.approved_name, api_key=key,
            )
        claim.consumed_at = timezone.now()
        claim.save(update_fields=["consumed_at", "updated_at"])
    response = JsonResponse({"status": "paired", "device_id": str(device.id),
                             "api_key": issued.plaintext})
    response["Cache-Control"] = "no-store"
    return response


@login_required
@require_http_methods(["POST"])
def revoke_device(request, device_id):
    with transaction.atomic():
        device = ConnectedDevice.objects.select_for_update().filter(pk=device_id, owner=request.user).first()
        if not device:
            return error("Device not found.", 404)
        device.revoked_at = timezone.now()
        device.save(update_fields=["revoked_at", "updated_at"])
        if device.api_key_id:
            UserApiKey.objects.filter(pk=device.api_key_id, owner=request.user,
                                      revoked_at__isnull=True).update(revoked_at=timezone.now())
    return JsonResponse({"item": describe(device)})


@login_required
@require_http_methods(["PATCH", "DELETE"])
def device_detail(request, device_id):
    if request.method == "PATCH":
        return edit_device(request, device_id)
    return delete_device(request, device_id)


def delete_device(request, device_id):
    """Permanently remove an owned device record; never leave its token usable."""
    with transaction.atomic():
        device = ConnectedDevice.objects.select_for_update().filter(pk=device_id, owner=request.user).first()
        if not device:
            return error("Device not found.", 404)
        uid = device.device_uid
        if device.api_key_id:
            UserApiKey.objects.filter(pk=device.api_key_id, owner=request.user).update(revoked_at=timezone.now())
        # Old approved claims must not be able to complete and recreate a deleted device.
        DevicePairing.objects.filter(device_uid=uid).delete()
        device.delete()
    response = JsonResponse({"deleted": True})
    response["Cache-Control"] = "no-store"
    return response


@login_required
@require_http_methods(["PATCH"])
def edit_device(request, device_id):
    """Update a paired device and its existing scoped key without issuing a new secret."""
    if not request.user.is_active:
        return error("Account is inactive.", 403)
    try:
        data = payload(request)
        if not data or set(data) - {"name", "scopes"}:
            return error("Only name and scopes may be edited.")
        scopes = list(validate_scopes(data["scopes"])) if "scopes" in data else None
        name = data.get("name")
        if name is not None and (not isinstance(name, str) or not 1 <= len(name.strip()) <= 120):
            return error("Device name must be 1–120 characters.")
    except (ValueError, TypeError, json.JSONDecodeError) as exc:
        return error(str(exc))
    with transaction.atomic():
        device = ConnectedDevice.objects.select_for_update(of=("self",)).filter(
            pk=device_id, owner=request.user, revoked_at__isnull=True
        ).first()
        if not device or not device.api_key or not device.api_key.is_active():
            return error("Active paired device not found.", 404)
        if scopes is not None and not set(scopes) <= DEVICE_SCOPES[device.device_type]:
            return error("Unsupported scope for this device type.")
        key = UserApiKey.objects.select_for_update().get(pk=device.api_key_id, owner=request.user)
        if not key.is_active():
            return error("Device API key is inactive.", 409)
        if scopes is not None:
            key.scopes = scopes
        if name is not None:
            device.name = name.strip()
            key.name = device.name
            device.save(update_fields=["name", "updated_at"])
        key.full_clean()
        key.save(update_fields=["scopes", "name", "updated_at"])
        device.api_key = key
    response = JsonResponse({"item": describe(device)})
    response["Cache-Control"] = "no-store"
    return response


@require_http_methods(["POST"])
@require_device_scope("devices:status")
def device_heartbeat(request):
    """A successful authenticated heartbeat indicates API reachability, not Wi-Fi or sensor health."""
    try:
        info = payload(request)
        version = info.get("firmware_version", "")
        capabilities = info.get("capabilities", [])
        reported = info.get("status", {})
        if not isinstance(reported, dict) or set(reported) - {"wifi", "api", "hardware"} or any(
            not isinstance(v, str) or v not in {"connected", "disconnected", "ok", "degraded", "error", "unknown"}
            for v in reported.values()
        ):
            raise ValueError("Invalid device status.")
        if not isinstance(version, str) or len(version) > 80:
            raise ValueError("Invalid firmware version.")
        if not isinstance(capabilities, list) or len(capabilities) > 25 or any(
            not isinstance(x, str) or len(x) > 60 for x in capabilities
        ):
            raise ValueError("Invalid capabilities.")
    except (ValueError, TypeError, json.JSONDecodeError) as exc:
        return error(str(exc))
    updated = ConnectedDevice.objects.filter(owner=request.device_owner, api_key=request.device_key,
                                              revoked_at__isnull=True).update(
        last_seen_at=timezone.now(), firmware_version=version, capabilities=capabilities,
        reported_status=reported)
    if not updated:
        return error("No active connected device is bound to this credential.", 403)
    return JsonResponse({"status": "ok"})
