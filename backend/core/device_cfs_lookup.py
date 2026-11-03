"""Read-only lookup of an already scanned CFS/MIFARE Classic RFID UID.

The terminal may optionally send decoded material metadata for display, but
those untrusted fields never create, edit or select a spool. UID association is
the only authoritative inventory match.
"""
import re

from django.db.models import Q
from django.http import JsonResponse
from django.views.decorators.http import require_http_methods

from .device_api_views import _error, require_device_scope
from .models import Spool, PrinterMaterialDatabaseSnapshot

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
        Spool.objects.filter(owner=owner).filter(Q(rfid_uid=uid) | Q(rfid_uid_secondary=uid))
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


MATERIAL_ID_PATTERN = re.compile(r"^[0-9]{5}$")


@require_http_methods(["GET"])
@require_device_scope("inventory:read")
def material_by_id(request):
    """Resolve a decoded CFS material code against the owner's saved printer snapshots.

    No printer access or database writes. Exact five-character IDs only.
    Never interpret a material match as proof of physical spool ownership.
    """
    owner = request.device_owner
    if not owner.has_perm("core.view_printer"):
        return _error("Owner is not permitted to view printer materials.", 403)
    if set(request.GET) != {"id"}:
        return _error("Provide only a material ID.", 400)
    material_id = request.GET.get("id", "")
    if not MATERIAL_ID_PATTERN.fullmatch(material_id):
        return _error("Material ID must be exactly five digits.", 400)
    matches = []
    snapshots = PrinterMaterialDatabaseSnapshot.objects.filter(
        connection__printer__owner=owner, connection__adapter="creality_local",
    ).select_related("connection__printer").order_by("-synced_at")
    for snap in snapshots:
        payload = snap.payload
        result = payload.get("result") if isinstance(payload, dict) else None
        entries = result.get("list") if isinstance(result, dict) else None
        if not isinstance(entries, list):
            continue
        for entry in entries:
            base = entry.get("base") if isinstance(entry, dict) else None
            if not isinstance(base, dict) or base.get("id") != material_id:
                continue
            matches.append({
                "id": material_id,
                "manufacturer": str(base.get("brand") or "")[:80],
                "name": str(base.get("name") or "")[:120],
                "printer_id": str(snap.connection.printer_id),
                "synced_at": snap.synced_at.isoformat(),
            })
            break
    if not matches:
        return JsonResponse({"found": False, "id": material_id, "status": "unmatched"})
    # Different printers may assign different names to the same material ID.
    names = {(row["manufacturer"], row["name"]) for row in matches}
    if len(names) != 1:
        return JsonResponse({"found": False, "id": material_id, "status": "ambiguous"})
    match = matches[0]
    return JsonResponse({
        "found": True, "id": material_id, "status": "matched",
        "manufacturer": match["manufacturer"], "name": match["name"],
        "source": "printer_material_database", "synced_at": match["synced_at"],
    })
