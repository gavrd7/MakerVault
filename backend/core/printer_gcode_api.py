"""Owner-scoped printer G-code library and explicit submission endpoints."""
import uuid
import re

from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.views.decorators.http import require_http_methods

from .models import PrinterConnection, PrinterGcodeSubmission
from .printer_gcode_submission import (
    GcodeSubmissionError, availability, list_printer_gcodes, inspect_printer_file, submit,
)
from .api_views import _require_permission, _read_json


def _connection(user, printer_id, connection_id):
    return PrinterConnection.objects.select_related(
        "printer", "printer__catalog_model", "printer__printer_manufacturer"
    ).filter(
        id=connection_id, printer_id=printer_id, printer__owner=user
    ).first()


@login_required
@require_http_methods(["GET"])
def files(request, printer_id, connection_id):
    connection = _connection(request.user, printer_id, connection_id)
    if not connection:
        return JsonResponse({"error": "Printer connection not found."}, status=404)
    if "inspect_path" in request.GET:
        try:
            report = inspect_printer_file(connection, request.GET["inspect_path"])
        except GcodeSubmissionError as exc:
            return JsonResponse({"error": str(exc), "inspection_available": False}, status=exc.status)
        return JsonResponse({"analysis": report, "inspection_available": True})
    caps = availability(connection)
    if connection.adapter == "bambu_local" and caps["browse_requires_pin"]:
        return JsonResponse({
            "capabilities": caps, "rows": [],
            "notice": "Read-only Bambu FTPS listing is available experimentally after you configure "
                      "the printer's independently verified SHA-256 TLS certificate fingerprint. "
                      "G-code transfer/start remains disabled.",
        })
    if not caps["can_browse"]:
        return JsonResponse({
            "capabilities": caps, "rows": [],
            "notice": "No documented G-code storage protocol is enabled for this monitoring adapter. "
                      "Transfer and printing remain unavailable until the protocol is implemented and validated.",
        })
    if not caps["online"]:
        return JsonResponse({"capabilities": caps, "rows": [],
                             "notice": "Printer file browsing requires a current online connection."})
    try:
        rows = list_printer_gcodes(connection)
    except GcodeSubmissionError as exc:
        if connection.adapter == "creality_local":
            # File listing and upload are separate stock interfaces. A failed
            # read-only storage probe must not hide native upload capability.
            return JsonResponse({"capabilities": caps, "rows": [], "error": str(exc)})
        return JsonResponse({"capabilities": caps, "rows": [], "error": str(exc)}, status=exc.status)
    return JsonResponse({
        "capabilities": caps, "rows": rows,
        "notice": ("Experimental read-only Bambu FTPS listing: printing is not enabled."
                   if connection.adapter == "bambu_local" else ""),
    })


@login_required
@require_http_methods(["PATCH"])
def bambu_certificate(request, printer_id, connection_id):
    """Configure a pinned Bambu FTPS device certificate, never auto-trust it."""
    connection = _connection(request.user, printer_id, connection_id)
    if not connection or connection.adapter != "bambu_local":
        return JsonResponse({"error": "Bambu printer connection not found."}, status=404)
    denied = _require_permission(request, "core.change_printer")
    if denied:
        return denied
    try:
        payload = _read_json(request)
    except ValueError as exc:
        return JsonResponse({"error": str(exc)}, status=400)
    if not isinstance(payload, dict) or set(payload) != {"sha256"}:
        return JsonResponse({"error": "Supply only an independently verified certificate SHA-256 fingerprint."}, status=400)
    value = str(payload.get("sha256") or "").replace(":", "").strip().lower()
    if value and not re.fullmatch(r"[0-9a-f]{64}", value):
        return JsonResponse({"error": "Certificate SHA-256 must contain exactly 64 hexadecimal characters."}, status=400)
    config = dict(connection.config or {})
    if value:
        config["bambu_ftps_cert_sha256"] = value
    else:
        config.pop("bambu_ftps_cert_sha256", None)
    connection.config = config
    connection.save(update_fields=["config", "updated_at"])
    return JsonResponse({"certificate_pinned": bool(value), "fingerprint": value})


@login_required
@require_http_methods(["PATCH"])
def submission_opt_in(request, printer_id, connection_id):
    """Explicit owner-controlled opt-in for experimental native file transfers."""
    connection = _connection(request.user, printer_id, connection_id)
    if not connection or connection.adapter not in {"prusa", "flashforge", "creality_local"}:
        return JsonResponse({"error": "Native G-code transfer is not available for this adapter."}, status=404)
    denied = _require_permission(request, "core.change_printer")
    if denied:
        return denied
    try:
        payload = _read_json(request)
    except ValueError as exc:
        return JsonResponse({"error": str(exc)}, status=400)
    if not isinstance(payload, dict) or set(payload) - {"enabled", "single_spool_start"} or not isinstance(payload.get("enabled"), bool) or ("single_spool_start" in payload and not isinstance(payload["single_spool_start"], bool)):
        return JsonResponse({"error": "Enable or disable native G-code transfer explicitly."}, status=400)
    config = dict(connection.config or {})
    if payload["enabled"]:
        config["gcode_submission_enabled"] = True
    else:
        config.pop("gcode_submission_enabled", None)
        config.pop("creality_single_spool_start_enabled", None)
    if connection.adapter == "creality_local" and "single_spool_start" in payload:
        if payload["single_spool_start"] and not payload["enabled"]:
            return JsonResponse({"error": "Enable Creality G-code transfer before native print-start."}, status=400)
        if payload["single_spool_start"]:
            config["creality_single_spool_start_enabled"] = True
        else:
            config.pop("creality_single_spool_start_enabled", None)
    connection.config = config
    connection.save(update_fields=["config", "updated_at"])
    return JsonResponse({"enabled": payload["enabled"], "single_spool_start": bool(config.get("creality_single_spool_start_enabled"))})


@login_required
@require_http_methods(["POST"])
def submit_file(request, printer_id, connection_id):
    connection = _connection(request.user, printer_id, connection_id)
    if not connection:
        return JsonResponse({"error": "Printer connection not found."}, status=404)
    denied = _require_permission(request, "core.change_printer")
    if denied:
        return denied
    try:
        payload = _read_json(request)
        receipt = submit(connection, request.user, payload)
    except (GcodeSubmissionError, ValueError) as exc:
        return JsonResponse({"error": str(exc)}, status=getattr(exc, "status", 400))
    return JsonResponse({"submission": receipt}, status=202)


@login_required
@require_http_methods(["GET"])
def submission_status(request, printer_id, connection_id, request_id):
    connection = _connection(request.user, printer_id, connection_id)
    if not connection:
        return JsonResponse({"error": "Printer connection not found."}, status=404)
    row = PrinterGcodeSubmission.objects.filter(
        pk=request_id, connection=connection, requested_by=request.user
    ).first()
    if not row:
        return JsonResponse({"error": "Submission not found."}, status=404)
    return JsonResponse({"submission": {
        "request_id": str(row.pk), "source": row.source, "action": row.action,
        "remote_path": row.remote_path, "status": row.status,
        "message": row.message,
    }})
