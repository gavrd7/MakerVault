"""Weigh-station preview and confirmed history; bearer-only device routes."""
import json
import hashlib
from django.core import signing
from decimal import Decimal, InvalidOperation
from uuid import UUID

from django.db import transaction
from django.http import JsonResponse
from django.views.decorators.http import require_http_methods

from .device_api_views import require_device_scope, _error, MAX_JSON_BYTES
from .models import DeviceWeightMeasurement, Spool, PrintedPart, Project, ReusableSpool, MakerTag

TARGETS = {"spool": Spool, "printed_part": PrintedPart, "project": Project}
MAX_WEIGHT_G = Decimal("1000000.00")
PREVIEW_TTL_SECONDS = 300


def _parse(request):
    if len(request.body) > MAX_JSON_BYTES:
        raise OverflowError()
    try:
        data = json.loads(request.body)
    except (ValueError, UnicodeDecodeError) as exc:
        raise ValueError("Invalid JSON.") from exc
    if not isinstance(data, dict) or not {"request_id", "target_type", "target_id", "gross_weight_g", "tare_weight_g", "update_inventory"} <= set(data) or set(data) - {"request_id", "target_type", "target_id", "gross_weight_g", "tare_weight_g", "update_inventory", "preview_receipt"}:
        raise ValueError("Unexpected or missing fields.")
    if data["target_type"] not in TARGETS or not isinstance(data["update_inventory"], bool):
        raise ValueError("Unsupported target or operation.")
    try:
        data["request_id"] = UUID(data["request_id"])
        data["target_id"] = UUID(data["target_id"])
        for field in ("gross_weight_g", "tare_weight_g"):
            value = data[field]
            if not isinstance(value, str) or len(value) > 14:
                raise ValueError("Weights must be decimal strings.")
            number = Decimal(value)
            if not number.is_finite() or number < 0 or number > MAX_WEIGHT_G or number.as_tuple().exponent < -2:
                raise ValueError("Weight out of range.")
            data[field] = number
    except (ValueError, TypeError, InvalidOperation, AttributeError) as exc:
        raise ValueError("Invalid UUID or weight.") from exc
    if data["tare_weight_g"] > data["gross_weight_g"]:
        raise ValueError("Tare exceeds gross.")
    if data["update_inventory"] and data["target_type"] != "spool":
        raise ValueError("Only filament spools support inventory weight updates.")
    return data


def _preview_fingerprint(owner, data):
    fields = {
        "owner": owner.pk,
        "request_id": str(data["request_id"]),
        "target_type": data["target_type"],
        "target_id": str(data["target_id"]),
        "gross_weight_g": str(data["gross_weight_g"]),
        "tare_weight_g": str(data["tare_weight_g"]),
        "update_inventory": data["update_inventory"],
    }
    return hashlib.sha256(json.dumps(fields, sort_keys=True).encode()).hexdigest()


def _tare_details(owner, target):
    reel = ReusableSpool.objects.filter(owner=owner, filament_spool=target).select_related("design").first()
    if reel is None:
        return {"source": "manual", "weight_g": None, "reel_id": None}
    tare = reel.effective_tare_g
    return {
        "source": "measured_reusable_spool" if reel.measured_tare_g is not None else (
            "nominal_reusable_spool" if tare is not None else "unknown"
        ),
        "weight_g": str(tare) if tare is not None else None,
        "reel_id": str(reel.pk),
    }


def _target(owner, kind, pk, *, lock=False):
    model = TARGETS[kind]
    manager = model.objects.select_for_update() if lock else model.objects
    return manager.filter(owner=owner, pk=pk).first()


def _check_permission(owner, kind, *, update):
    model = TARGETS[kind]
    action = "change" if update else "view"
    return owner.has_perm(f"core.{action}_{model._meta.model_name}")


def _result(data, record=None):
    net = data["gross_weight_g"] - data["tare_weight_g"]
    return {
        "request_id": str(data["request_id"]),
        "target_type": data["target_type"],
        "target_id": str(data["target_id"]),
        "gross_weight_g": str(data["gross_weight_g"]),
        "tare_weight_g": str(data["tare_weight_g"]),
        "net_weight_g": str(net),
        "update_inventory": data["update_inventory"],
        "measurement_id": str(record.pk) if record else None,
    }


def _parse_error(request):
    try:
        return _parse(request), None
    except OverflowError:
        return None, _error("Request is too large.", 413)
    except ValueError:
        return None, _error("Invalid measurement payload.", 400)


@require_http_methods(["POST"])
@require_device_scope("spools:weight")
def preview_measurement(request):
    data, error = _parse_error(request)
    if error:
        return error
    owner = request.device_owner
    if not _check_permission(owner, data["target_type"], update=data["update_inventory"]):
        return _error("Insufficient record permission.", 403)
    if not _target(owner, data["target_type"], data["target_id"]):
        return _error("Record not found.", 404)
    preview = _result(data)
    if data["target_type"] == "spool":
        spool = _target(owner, "spool", data["target_id"])
        preview["known_tare"] = _tare_details(owner, spool)
    receipt = signing.dumps(_preview_fingerprint(owner, data), salt="device-weigh-preview-v1")
    return JsonResponse({"preview": preview, "preview_receipt": receipt, "expires_in_seconds": PREVIEW_TTL_SECONDS, "requires_confirmation": True})


@require_http_methods(["POST"])
@require_device_scope("spools:weight")
def confirm_measurement(request):
    data, error = _parse_error(request)
    if error:
        return error
    owner = request.device_owner
    if not _check_permission(owner, data["target_type"], update=data["update_inventory"]):
        return _error("Insufficient record permission.", 403)
    receipt = data.get("preview_receipt")
    if not isinstance(receipt, str) or len(receipt) > 512:
        return _error("A valid measurement preview must be confirmed.", 400)
    try:
        fingerprint = signing.loads(receipt, salt="device-weigh-preview-v1", max_age=PREVIEW_TTL_SECONDS)
    except signing.BadSignature:
        return _error("Measurement preview expired or invalid; preview again.", 409)
    if fingerprint != _preview_fingerprint(owner, data):
        return _error("Measurement changed after preview; preview again.", 409)
    with transaction.atomic():
        existing = DeviceWeightMeasurement.objects.filter(owner=owner, request_id=data["request_id"]).first()
        if existing:
            if (existing.target_type != data["target_type"] or existing.target_id != data["target_id"]
                    or existing.gross_weight_g != data["gross_weight_g"]
                    or existing.tare_weight_g != data["tare_weight_g"]
                    or existing.updated_spool != data["update_inventory"]):
                return _error("Request ID already used for a different measurement.", 409)
            return JsonResponse({"created": False, "measurement": _result(data, existing)})
        target = _target(owner, data["target_type"], data["target_id"], lock=True)
        if target is None:
            return _error("Record not found.", 404)
        prior = None
        if data["update_inventory"]:
            known_tare = _tare_details(owner, target)
            if known_tare["weight_g"] is not None:
                if data["tare_weight_g"] != Decimal(known_tare["weight_g"]):
                    return _error("Known reusable-spool tare changed or does not match; preview again.", 409)
            elif data["tare_weight_g"] <= 0:
                return _error("A confirmed nonzero physical tare is required when no reusable-spool tare is known.", 400)
            # The preview receipt binds the operator-confirmed tare, target and reading.
            prior = target.remaining_weight_g
            target.remaining_weight_g = data["gross_weight_g"] - data["tare_weight_g"]
            target.save(update_fields=["remaining_weight_g", "updated_at"])
        record = DeviceWeightMeasurement.objects.create(
            owner=owner, api_key=request.device_key, request_id=data["request_id"],
            target_type=data["target_type"], target_id=data["target_id"],
            gross_weight_g=data["gross_weight_g"], tare_weight_g=data["tare_weight_g"],
            net_weight_g=data["gross_weight_g"] - data["tare_weight_g"],
            updated_spool=data["update_inventory"], previous_spool_weight_g=prior,
        )
    return JsonResponse({"created": True, "measurement": _result(data, record)}, status=201)


@require_http_methods(["POST"])
@require_device_scope("spools:weight")
def identify_spool(request):
    """Locate an owned spool by its active Maker Tag or legacy RFID UID."""
    if len(request.body) > MAX_JSON_BYTES:
        return _error("Request is too large.", 413)
    try:
        data = json.loads(request.body)
    except (ValueError, UnicodeDecodeError):
        return _error("Invalid identification payload.", 400)
    if not isinstance(data, dict) or set(data) != {"kind", "uid"}:
        return _error("Provide kind and uid.", 400)
    kind, uid = data["kind"], data["uid"]
    if not isinstance(kind, str) or kind not in ("nfc", "rfid") or not isinstance(uid, str):
        return _error("Unsupported RFID identity.", 400)
    compact = uid.replace(":", "").replace("-", "").replace(" ", "")
    if len(compact) not in (8, 14, 20) or any(c not in "0123456789abcdefABCDEF" for c in compact):
        return _error("Invalid RFID UID.", 400)
    owner = request.device_owner
    if not owner.has_perm("core.view_spool"):
        return _error("Insufficient spool permission.", 403)
    code = compact.upper()
    tag = MakerTag.objects.filter(owner=owner, kind=kind, code=code, status="active", target_type="spool").first()
    spool = Spool.objects.filter(owner=owner, pk=tag.target_id).first() if tag else None
    if spool is None and kind == "rfid":
        spool = Spool.objects.filter(owner=owner, rfid_uid=code).first()
    if spool is None:
        return JsonResponse({"found": False, "kind": kind, "uid": code})
    return JsonResponse({
        "found": True, "spool": {
            "id": str(spool.pk), "spool_id": spool.spool_id,
            "remaining_weight_g": str(spool.remaining_weight_g) if spool.remaining_weight_g is not None else None,
            "known_tare": _tare_details(owner, spool),
        },
    })


@require_http_methods(["GET"])
@require_device_scope("spools:weight")
def measurement_history(request):
    kind, identifier = request.GET.get("target_type"), request.GET.get("target_id")
    if kind not in TARGETS:
        return _error("Unsupported measurement target.", 400)
    try:
        pk = UUID(identifier)
    except (ValueError, TypeError, AttributeError):
        return _error("Invalid target ID.", 400)
    owner = request.device_owner
    if not _check_permission(owner, kind, update=False):
        return _error("Insufficient record permission.", 403)
    if _target(owner, kind, pk) is None:
        return _error("Record not found.", 404)
    rows = DeviceWeightMeasurement.objects.filter(owner=owner, target_type=kind, target_id=pk).order_by("-recorded_at")[:25]
    return JsonResponse({"rows": [
        {
            "id": str(record.pk), "recorded_at": record.recorded_at.isoformat(),
            "gross_weight_g": str(record.gross_weight_g),
            "tare_weight_g": str(record.tare_weight_g),
            "net_weight_g": str(record.net_weight_g),
            "updated_spool": record.updated_spool,
            "previous_spool_weight_g": str(record.previous_spool_weight_g) if record.previous_spool_weight_g is not None else None,
        }
        for record in rows
    ]})
