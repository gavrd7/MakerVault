"""Authenticated MakerVault endpoints for opt-in manual HA printer power."""
import json

from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.views.decorators.http import require_http_methods
from django.utils import timezone

from .home_assistant_power import (
    HomeAssistantPowerError, encrypt_token, get_switches, printer_is_busy,
    set_switch, switch_state, valid_entity, validate_url, ha_request,
)
from .models import Printer, PrintingIntegrationSetting
from .user_admin import can_manage_workspace_settings


def _error(message, status=400):
    return JsonResponse({"error": str(message)}, status=status)


def _body(request):
    try:
        data = json.loads(request.body.decode("utf-8"))
    except (ValueError, UnicodeError) as exc:
        raise HomeAssistantPowerError("Invalid request.") from exc
    if not isinstance(data, dict) or len(request.body) > 8192:
        raise HomeAssistantPowerError("Invalid request.")
    return data


def _setting(owner):
    return PrintingIntegrationSetting.objects.filter(
        owner=owner, provider="homeassistant",
    ).first()


def _public(row):
    config = row.config or {}
    return {
        "enabled": row.enabled, "endpoint_url": row.endpoint_url,
        "token_configured": bool(config.get("encrypted_token")),
        "status": row.status, "last_checked_at": row.last_checked_at.isoformat()
        if row.last_checked_at else None,
    }


@login_required
@require_http_methods(["GET", "PATCH"])
def home_assistant_settings(request):
    if not can_manage_workspace_settings(request.user):
        return _error("Administrator access is required.", 403)
    row, _ = PrintingIntegrationSetting.objects.get_or_create(
        owner=request.user, provider="homeassistant",
        defaults={"enabled": False, "status": "not_configured"},
    )
    if request.method == "GET":
        return JsonResponse({"item": _public(row)})
    try:
        data = _body(request)
        if set(data) - {"enabled", "endpoint_url", "token", "clear_token"}:
            raise HomeAssistantPowerError("Unknown Home Assistant setting.")
        if "endpoint_url" in data:
            endpoint = str(data["endpoint_url"] or "").strip()
            row.endpoint_url = validate_url(endpoint) if endpoint else ""
        config = dict(row.config or {})
        if data.get("clear_token") is True:
            config.pop("encrypted_token", None)
        if data.get("token"):
            config["encrypted_token"] = encrypt_token(data["token"])
        row.config = config
        if "enabled" in data:
            if not isinstance(data["enabled"], bool):
                raise HomeAssistantPowerError("Enable must be a boolean.")
            row.enabled = data["enabled"]
        if row.enabled and (not row.endpoint_url or not config.get("encrypted_token")):
            raise HomeAssistantPowerError("Configure a Home Assistant server and token before enabling.")
        row.status = "ready" if row.enabled else "disabled"
        row.auto_sync = False
        row.next_sync_at = None
        row.save()
    except HomeAssistantPowerError as exc:
        return _error(exc)
    return JsonResponse({"item": _public(row)})


@login_required
@require_http_methods(["POST"])
def home_assistant_test(request):
    if not can_manage_workspace_settings(request.user):
        return _error("Administrator access is required.", 403)
    row = _setting(request.user)
    try:
        payload = ha_request(row, "GET", "/api/")
        if not isinstance(payload, dict) or payload.get("message") != "API running.":
            raise HomeAssistantPowerError("Home Assistant did not return the expected API response.")
        row.status = "connected"
        row.last_checked_at = timezone.now()
        row.last_error = ""
        row.save(update_fields=["status", "last_checked_at", "last_error", "updated_at"])
    except HomeAssistantPowerError as exc:
        return _error(exc, 502)
    return JsonResponse({"connected": True})


@login_required
@require_http_methods(["GET"])
def home_assistant_switches(request):
    if not can_manage_workspace_settings(request.user):
        return _error("Administrator access is required.", 403)
    try:
        return JsonResponse({"switches": get_switches(_setting(request.user))})
    except HomeAssistantPowerError as exc:
        return _error(exc, 502)


@login_required
@require_http_methods(["GET", "PATCH"])
def printer_power_assignment(request, printer_id):
    if not can_manage_workspace_settings(request.user):
        return _error("Administrator access is required.", 403)
    printer = Printer.objects.filter(owner=request.user, pk=printer_id).first()
    if not printer:
        return _error("Printer not found.", 404)
    row = _setting(request.user)
    if request.method == "GET":
        return JsonResponse({"entity_id": str((printer.profile_data or {}).get("ha_power_entity") or "")})
    try:
        if not row or not row.enabled:
            raise HomeAssistantPowerError("Enable Home Assistant before assigning a switch.")
        data = _body(request)
        if set(data) != {"entity_id"}:
            raise HomeAssistantPowerError("Choose one switch.")
        entity = data["entity_id"]
        if entity and not valid_entity(entity):
            raise HomeAssistantPowerError("Choose a valid switch entity.")
        if entity and entity not in {s["entity_id"] for s in get_switches(row)}:
            raise HomeAssistantPowerError("Selected switch is unavailable in Home Assistant.")
        # Prevent two printers being accidentally wired to the same smart plug.
        if entity and Printer.objects.filter(
            owner=request.user, profile_data__ha_power_entity=entity,
        ).exclude(pk=printer.pk).exists():
            raise HomeAssistantPowerError("That smart plug is already assigned to another printer.")
        data = dict(printer.profile_data or {})
        if entity:
            data["ha_power_entity"] = entity
        else:
            data.pop("ha_power_entity", None)
        printer.profile_data = data
        printer.save(update_fields=["profile_data", "updated_at"])
    except HomeAssistantPowerError as exc:
        return _error(exc)
    return JsonResponse({"entity_id": entity})


@login_required
@require_http_methods(["GET", "POST"])
def printer_power(request, printer_id):
    printer = Printer.objects.filter(owner=request.user, pk=printer_id).first()
    if not printer:
        return _error("Printer not found.", 404)
    # Hide the control entirely for users without permission to operate it.
    if not request.user.has_perm("core.change_printer"):
        return JsonResponse({"available": False}) if request.method == "GET" else _error("Printer control permission required.", 403)
    row = _setting(request.user)
    entity = (printer.profile_data or {}).get("ha_power_entity")
    if not row or not row.enabled or not valid_entity(entity):
        return JsonResponse({"available": False}) if request.method == "GET" else _error("Printer power is not configured.", 404)
    if request.method == "GET":
        try:
            state = switch_state(row, entity)
        except HomeAssistantPowerError as exc:
            return _error(exc, 502)
        return JsonResponse({"available": True, "state": state})
    try:
        data = _body(request)
        if set(data) - {"action", "confirm"} or data.get("action") not in {"on", "off"}:
            raise HomeAssistantPowerError("Choose power on or off.")
        if data["action"] == "off" and data.get("confirm") is not True:
            raise HomeAssistantPowerError("Explicit confirmation is required before cutting printer power.")
        if data["action"] == "off" and printer_is_busy(printer):
            return _error("Printer is active or cooling. Power off is blocked.", 409)
        state = set_switch(row, entity, data["action"])
    except HomeAssistantPowerError as exc:
        return _error(exc, 502)
    return JsonResponse({"available": True, "state": state})
