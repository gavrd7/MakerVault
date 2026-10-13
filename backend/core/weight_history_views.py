"""Session-authenticated measurement history for existing MakerVault detail pages."""
from uuid import UUID

from django.contrib.auth.decorators import login_required, permission_required
from django.http import JsonResponse
from django.views.decorators.http import require_GET

from .device_measurements import TARGETS
from .models import DeviceWeightMeasurement


@login_required
@require_GET
def weight_history(request):
    kind, value = request.GET.get("target_type"), request.GET.get("target_id")
    if kind not in TARGETS:
        return JsonResponse({"error": "Unsupported measurement target."}, status=400)
    try:
        target_id = UUID(value)
    except (TypeError, AttributeError, ValueError):
        return JsonResponse({"error": "Invalid record ID."}, status=400)
    model = TARGETS[kind]
    if not request.user.has_perm(f"core.view_{model._meta.model_name}"):
        return JsonResponse({"error": "Insufficient record permission."}, status=403)
    if not model.objects.filter(owner=request.user, pk=target_id).exists():
        return JsonResponse({"error": "Record not found."}, status=404)
    try:
        limit = int(request.GET.get("limit", "5"))
    except (TypeError, ValueError):
        return JsonResponse({"error": "Invalid limit."}, status=400)
    if not 1 <= limit <= 100:
        return JsonResponse({"error": "Limit must be between 1 and 100."}, status=400)
    base = DeviceWeightMeasurement.objects.filter(owner=request.user, target_type=kind, target_id=target_id)
    rows = base.order_by("-recorded_at", "-pk")[:limit]
    return JsonResponse({
        "total": base.count(),
        "rows": [{
            "id": str(item.pk),
            "recorded_at": item.recorded_at.isoformat(),
            "gross_weight_g": str(item.gross_weight_g),
            "tare_weight_g": str(item.tare_weight_g),
            "net_weight_g": str(item.net_weight_g),
            "updated_spool": item.updated_spool,
            "previous_spool_weight_g": str(item.previous_spool_weight_g) if item.previous_spool_weight_g is not None else None,
        } for item in rows],
    })
