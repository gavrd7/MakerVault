"""Read-only lookup of an already scanned CFS/MIFARE Classic RFID UID.

The terminal may optionally send decoded material metadata for display, but
those untrusted fields never create, edit or select a spool. UID association is
the only authoritative inventory match.
"""
import re

from django.http import JsonResponse
from django.views.decorators.http import require_http_methods

from .device_api_views import _error, require_device_scope
from .models import Spool

UID_PATTERN = re.compile(r"^[0-9A-F]{8}(?:[0-9A-F]{6})?(?:[0-9A-F]{6})?$")


@require_http_methods(["GET"])
@require_device_scope("inventory:read")
def spool_by_rfid(request):
    owner = request.device_owner
    if not owner.has_perm("core.view_spool"):
        return _error("Owner is not permitted to view spools.", 403)
    if set(request.GET) != {"uid"}:
        return _error("Provide only a tag UID.", 400)
    raw_uid = request.GET.get("uid", "")
    if not isinstance(raw_uid, str) or len(raw_uid) > 32:
        return _error("Invalid tag UID.", 400)
    uid = raw_uid.replace(":", "").replace("-", "").replace(" ", "").upper()
    if not UID_PATTERN.fullmatch(uid):
        return _error("UID must contain 4, 7 or 10 hexadecimal bytes.", 400)

    # Never match by material name/colour: CFS tags are user-programmable and
    # multiple physical spools can share the same filament metadata.
    spool = (
        Spool.objects.filter(owner=owner, rfid_uid=uid)
        .select_related("filament").first()
    )
    if spool is None:
        return JsonResponse({"found": False, "uid": uid, "status": "unmatched"})
    filament = spool.filament
    return JsonResponse({
        "found": True,
        "uid": uid,
        "status": "matched",
        "spool": {
            "id": str(spool.pk),
            "spool_id": spool.spool_id,
            "filament": str(filament),
            "material": filament.material,
            "color": filament.color_name,
            "color_hex": filament.color_hex,
            "remaining_weight_g": str(spool.remaining_weight_g) if spool.remaining_weight_g is not None else None,
        },
    })
