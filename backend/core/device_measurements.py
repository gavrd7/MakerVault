"""Weigh-station preview and confirmed history; bearer-only device routes."""
import json
from decimal import Decimal, InvalidOperation
from uuid import UUID

from django.db import transaction
from django.http import JsonResponse
from django.views.decorators.http import require_http_methods

from .device_api_views import require_device_scope, _error, MAX_JSON_BYTES
from .models import DeviceWeightMeasurement, Spool, PrintedPart, Project, ReusableSpool

TARGETS = {"spool": Spool, "printed_part": PrintedPart, "project": Project}
MAX_WEIGHT_G = Decimal("1000000.00")


def _parse(request):
    if len(request.body) > MAX_JSON_BYTES:
        raise OverflowError()
    try:
        data = json.loads(request.body)
    except (ValueError, UnicodeDecodeError) as exc:
        raise ValueError("Invalid JSON.") from exc
    if not isinstance(data, dict) or set(data) != {"request_id", "target_type", "target_id", "gross_weight_g", "tare_weight_g", "update_inventory"}:
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
    return JsonResponse({"preview": _result(data), "requires_confirmation": True})


@require_http_methods(["POST"])
@require_device_scope("spools:weight")
def confirm_measurement(request):
    data, error = _parse_error(request)
    if error:
        return error
    owner = request.device_owner
    if not _check_permission(owner, data["target_type"], update=data["update_inventory"]):
        return _error("Insufficient record permission.", 403)
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
            # Never infer tare from a label or from a product's nominal filament weight.
            # Confirmed client-supplied tare is recorded as provenance.
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
