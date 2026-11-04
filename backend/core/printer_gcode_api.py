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
    if not caps["supported"]:
        return JsonResponse({
            "capabilities": caps, "rows": [],
            "notice": "This monitoring adapter does not yet have validated G-code transfer support. "
                      "Bambu, PrusaLink, Creality-local and other proprietary file protocols "
                      "require separate implementations and physical hardware testing.",
        })
    if not caps["online"]:
        return JsonResponse({"capabilities": caps, "rows": [],
                             "notice": "Printer file browsing requires a current online connection."})
    try:
        rows = list_printer_gcodes(connection)
    except GcodeSubmissionError as exc:
        return JsonResponse({"capabilities": caps, "rows": [], "error": str(exc)}, status=exc.status)
    return JsonResponse({"capabilities": caps, "rows": rows})


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
