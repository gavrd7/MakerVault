"""Browser engine installation controller; never runs downloaded executables."""
import json
import os
import re
import uuid
from django.contrib.auth.decorators import login_required
from django.db import connection, transaction
from django.http import JsonResponse
from django.utils import timezone
from django.views.decorators.http import require_http_methods

from .models import SliceJob, SlicerEngineOperation, SlicerEngineAccessSettings
from .slicer_engine_installer_client import installer_request, EngineInstallerUnavailable
from .slicer_engines import get_engine

ACTIVE = ("queued", "downloading", "verifying", "staged", "activating")


def _serialize(op):
    return {
        "id": str(op.pk), "engine": op.engine, "version": op.version,
        "action": op.action, "status": op.status,
        "progress": op.progress, "message": op.status_message,
        "created_at": op.created_at.isoformat(),
        "completed_at": op.completed_at.isoformat() if op.completed_at else None,
    }


def _sync_operations(rows):
    if not isinstance(rows, list) or len(rows) > 30:
        return
    permitted = set(ACTIVE) | {"completed", "failed", "cancelled"}
    for row in rows:
        if not isinstance(row, dict) or row.get("status") not in permitted:
            continue
        try:
            operation_id = uuid.UUID(str(row["id"]))
        except (TypeError, ValueError, KeyError):
            continue
        operation = SlicerEngineOperation.objects.filter(pk=operation_id).first()
        if not operation or operation.status in {"completed", "failed", "cancelled"}:
            continue
        operation.status = row["status"]
        progress = row.get("progress")
        if isinstance(progress, int) and 0 <= progress <= 100:
            operation.progress = progress
        operation.status_message = str(row.get("message") or "")[:200]
        if operation.status in {"completed", "failed", "cancelled"}:
            operation.completed_at = timezone.now()
        operation.save(update_fields=["status", "progress", "status_message",
                                     "completed_at", "updated_at"])


@login_required
@require_http_methods(["GET", "POST"])
def engine_operations(request):
    policy = SlicerEngineAccessSettings.current()
    can_manage = request.user.is_superuser or not policy.restrict_engine_management_to_admins
    if request.method == "POST" and not can_manage:
        return JsonResponse({"error": "Engine changes are restricted by this installation."},
                            status=403)
    enabled = bool(os.environ.get("MAKERVAULT_SLICER_INSTALLER_URL"))

    if request.method == "GET":
        releases, connected, rollback_available = [], False, False
        installed = {}
        if enabled:
            try:
                report = installer_request("GET", "/status")
                _sync_operations(report.get("operations", []))
                rollback_available = report.get("rollback_available") is True
                installed = report.get("installed_versions", {})
                connected = True
            except EngineInstallerUnavailable:
                pass
            if connected:
                try:
                    releases = installer_request("GET", "/catalog").get("releases", [])
                except EngineInstallerUnavailable:
                    # GitHub may be offline without the local installer failing.
                    releases = []
        return JsonResponse({
            "approved_releases": releases if isinstance(releases, list) else [],
            "installed_versions": installed if isinstance(installed, dict) else {},
            "can_manage": can_manage,
            "restrict_to_admins": policy.restrict_engine_management_to_admins,
            "operations": [_serialize(op) for op in
                           SlicerEngineOperation.objects.order_by("-created_at")[:30]],
            "host_updater_connected": connected,
            "installation_available": bool(connected and releases),
            "rollback_available": bool(connected and rollback_available),
            "installation_note": "Downloads and integrity checks run automatically.",
        })

    if len(request.body) > 2048:
        return JsonResponse({"error": "Operation request is too large."}, status=413)
    try:
        data = json.loads(request.body)
    except (ValueError, UnicodeError):
        return JsonResponse({"error": "Invalid engine request."}, status=400)
    if not isinstance(data, dict) or set(data) != {
            "engine", "version", "action", "release_sha256"}:
        return JsonResponse({"error": "Invalid engine request."}, status=400)
    engine, version, action, digest = (
        data["engine"], data["version"], data["action"], data["release_sha256"])
    if any(not isinstance(x, str) for x in (engine, version, action, digest)):
        return JsonResponse({"error": "Invalid engine request."}, status=400)
    if action not in {"install", "update", "rollback", "activate", "uninstall"}:
        return JsonResponse({"error": "Unsupported engine operation."}, status=400)
    if action == "activate" and not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._+-]{0,79}", version):
        return JsonResponse({"error": "Invalid installed-engine version."}, status=400)
    try:
        get_engine(engine)
    except ValueError:
        return JsonResponse({"error": "Unsupported slicing engine."}, status=400)
    if not enabled:
        return JsonResponse({"error": "Engine installer is not configured."}, status=503)
    if SliceJob.objects.filter(status__in=("queued", "running")).exists():
        return JsonResponse({"error": "Please finish active slicing jobs first."}, status=409)

    # The installer independently resolves the selected official release and
    # verifies its published checksum. No browser-supplied download URL.
    with transaction.atomic():
        if connection.vendor == "postgresql":
            with connection.cursor() as cursor:
                cursor.execute("SELECT pg_advisory_xact_lock(%s)", [276381104])
        if SlicerEngineOperation.objects.filter(status__in=ACTIVE).exists():
            return JsonResponse({"error": "An engine update is already in progress."},
                                status=409)
        try:
            if action == "rollback":
                if engine != "crealityprint" or version != "previous" or digest != "0" * 64:
                    return JsonResponse({"error": "Invalid rollback request."}, status=400)
                response = installer_request("POST", "/rollback")
            elif action in {"activate", "uninstall"}:
                if (digest != "0" * 64
                        or (action == "uninstall" and version != "all")):
                    return JsonResponse({"error": "Invalid installed-engine operation."}, status=400)
                response = installer_request("POST", "/" + action, {
                    "engine": engine, "version": version,
                })
            else:
                response = installer_request("POST", "/install", {
                    "engine": engine, "version": version, "bundle_sha256": digest,
                })
            submitted = response["operation"]
            identity = uuid.UUID(submitted["id"])
            if (submitted["engine"] != engine or submitted["version"] != version
                    or submitted["status"] not in ACTIVE):
                raise ValueError("Unexpected installer response.")
        except (EngineInstallerUnavailable, ValueError, KeyError, TypeError):
            return JsonResponse({
                "error": "Installer could not start this version. Check the official release or installer status."
            }, status=503)
        record = SlicerEngineOperation.objects.create(
            id=identity, requested_by=request.user, engine=engine,
            version=version, action=action, release_sha256=digest,
            status="queued", status_message=("Preparing official engine download"
                  if action in {"install", "update"} else "Preparing installed engine change"),
        )
    return JsonResponse({"operation": _serialize(record)}, status=202)
