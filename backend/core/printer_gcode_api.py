"""Owner-scoped printer G-code library and explicit submission endpoints."""
import uuid

from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.views.decorators.http import require_http_methods

from .models import PrinterConnection, PrinterGcodeSubmission
from .printer_gcode_submission import (
    GcodeSubmissionError, availability, list_printer_gcodes, submit,
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
        return JsonResponse({"capabilities": caps, "rows": [], "error": str(exc)}, status=exc.status)
    return JsonResponse({
        "capabilities": caps, "rows": rows,
        "notice": ("Experimental read-only Bambu FTPS listing: printing is not enabled."
                   if connection.adapter == "bambu_local" else ""),
    })


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
