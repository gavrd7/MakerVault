"""Read-only engine inventory and administrator-controlled maintenance requests.

Never executes commands, writes to an engine volume, downloads remote bytes or
exposes secrets. A separately provisioned host maintenance agent can later
consume these durable, approved requests.
"""
import json
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.http import JsonResponse
from django.views.decorators.http import require_http_methods
from .models import SliceJob, SlicerEngineOperation
from .slicer_engine_releases import validated_releases, approved_release
from .slicer_engines import get_engine
from .slicer_execution import verified_installation


ACTIVE = ("queued", "downloading", "verifying", "staged", "activating")


def _serialize(op):
    return {
        "id": str(op.pk), "engine": op.engine, "version": op.version,
        "action": op.action, "status": op.status,
        "progress": op.progress, "message": op.status_message,
        "created_at": op.created_at.isoformat(),
        "completed_at": op.completed_at.isoformat() if op.completed_at else None,
    }


@login_required
@require_http_methods(["GET", "POST"])
def engine_operations(request):
    if not request.user.is_superuser:
        return JsonResponse({"error": "Only an administrator can manage slicer engines."}, status=403)
    if request.method == "GET":
        try:
            releases = validated_releases()
        except ValueError:
            return JsonResponse({"error": "Engine release catalogue is invalid."}, status=503)
        records = list(SlicerEngineOperation.objects.order_by("-created_at")[:30])
        return JsonResponse({
            "approved_releases": releases,
            "operations": [_serialize(op) for op in records],
            "host_updater_connected": False,
            "installation_available": False,
            "installation_note": ("Engine installs require a separately configured host "
                                  "updater and independently approved release bundles. "
                                  "The web application cannot modify containers."),
        })

    if len(request.body) > 2048:
        return JsonResponse({"error": "Engine operation request is too large."}, status=413)
    try:
        payload = json.loads(request.body)
    except (ValueError, UnicodeError):
        return JsonResponse({"error": "Invalid engine operation request."}, status=400)
    if not isinstance(payload, dict) or set(payload) != {
            "engine", "version", "action", "release_sha256"}:
        return JsonResponse({"error": "Invalid engine operation fields."}, status=400)
    engine, version, action, digest = (
        payload["engine"], payload["version"], payload["action"],
        payload["release_sha256"]
    )
    if any(not isinstance(value, str) for value in (engine, version, action, digest)):
        return JsonResponse({"error": "Invalid engine operation values."}, status=400)
    if action not in {"install", "update"}:
        return JsonResponse({"error": "Unsupported engine operation."}, status=400)
    try:
        get_engine(engine)
        approved_release(engine, version, digest)
    except ValueError:
        return JsonResponse({"error": "Engine release has not been independently approved."}, status=400)
    # The first phase is read-only until an authenticated host-maintenance
    # agent with a writeable, isolated engine volume has been provisioned.
    # Never queue operations that nothing can safely execute.
    return JsonResponse({
        "error": "The restricted host updater is not connected; installation is unavailable."
    }, status=503)
