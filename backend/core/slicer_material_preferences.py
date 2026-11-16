"""Owner-scoped, engine-specific remembered native filament presets.

Bindings follow the material identity rather than the CFS/AMS slot index.
Only real, currently loaded printer slots and owner-owned native filament
profiles can be associated. A changed filament never inherits the old
occupant's profile solely because it is in the same physical bay.
"""
import hashlib
import json
import re

from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.views.decorators.http import require_http_methods
from django.db import transaction

from .models import Printer, PrinterFilamentSlot, SlicerProfile, SlicerMaterialProfilePreference


def material_identity(slot):
    meta = slot.metadata if isinstance(slot.metadata, dict) else {}
    def norm(value):
        return re.sub(r"\s+", " ", str(value or "").strip()).casefold()
    spool = getattr(slot, "spool", None)
    filament = getattr(spool, "filament", None) if spool else None
    product = norm(meta.get("product_name"))
    vendor = norm(meta.get("vendor"))
    material = norm(slot.material or getattr(filament, "material", ""))
    colour = norm(slot.color_hex or slot.color_name or
                  getattr(filament, "color_hex", ""))
    code = norm(meta.get("material_code"))
    # A meaningful product identity is shared between identical replacement
    # spools and survives moving a spool between physical feeder slots.
    if product and material:
        identity = ["product", vendor, product, material, colour, code]
    elif slot.spool_id:
        identity = ["spool", str(slot.spool_id)]
    elif slot.rfid_uid:
        identity = ["rfid", norm(slot.rfid_uid)]
    elif material and colour:
        # Without a reliable product identity, constrain matching to this
        # physical bay so similarly coloured brands cannot cross-map.
        identity = ["bay", str(slot.pk), material, colour, code]
    else:
        return None
    return hashlib.sha256(json.dumps(identity, separators=(",", ":")).encode()).hexdigest()


def _failure(reason, status=400):
    return JsonResponse({"error": reason}, status=status)


@login_required
@require_http_methods(["GET", "POST"])
def material_preferences(request):
    if request.method == "POST":
        try:
            payload = json.loads(request.body)
        except (ValueError, UnicodeDecodeError):
            return _failure("Invalid material profile preference JSON.")
        if not isinstance(payload, dict) or set(payload) != {
                "printer_id", "slot_id", "engine", "version", "profile_id"}:
            return _failure("Invalid material profile preference payload.")
    else:
        payload = {
            "printer_id": request.GET.get("printer_id"),
            "engine": request.GET.get("engine"),
            "version": request.GET.get("version"),
        }
    engine, version = payload.get("engine"), payload.get("version")
    if (not isinstance(engine, str) or not re.fullmatch(r"[a-z0-9_-]{1,32}", engine)
            or not isinstance(version, str)
            or not re.fullmatch(r"[a-zA-Z0-9._-]{1,80}", version)):
        return _failure("Choose a valid slicer engine and version.")
    printer = Printer.objects.filter(pk=payload.get("printer_id"),
                                     owner=request.user).first()
    if not printer:
        return _failure("Printer unavailable.", 404)
    if request.method == "GET":
        slots = list(PrinterFilamentSlot.objects.filter(
            printer=printer, is_loaded=True).select_related("spool", "spool__filament"))
        identities = {str(slot.pk): material_identity(slot) for slot in slots}
        keys = {value for value in identities.values() if value}
        preferences = {
            row.material_key: row
            for row in SlicerMaterialProfilePreference.objects.filter(
                printer=printer, material_key__in=keys,
                engine=engine, engine_version=version,
                profile__owner=request.user, profile__engine=engine,
                profile__engine_version=version, profile__kind="filament",
            ).select_related("profile")
        }
        return JsonResponse({"assignments": [
            {"slot_id": slot_id, "profile_id": str(preferences[key].profile_id)}
            for slot_id, key in identities.items() if key in preferences
        ]})
    slot = PrinterFilamentSlot.objects.filter(
        pk=payload.get("slot_id"), printer=printer, is_loaded=True
    ).select_related("spool", "spool__filament").first()
    if not slot:
        return _failure("Loaded printer filament slot unavailable.", 404)
    key = material_identity(slot)
    if not key:
        return _failure("Filament identification is insufficient to remember this profile.")
    profile_id = payload.get("profile_id")
    if profile_id is not None:
        profile = SlicerProfile.objects.filter(
            pk=profile_id, owner=request.user, kind="filament",
            engine=engine, engine_version=version,
        ).first()
        if not profile:
            return _failure("Native filament preset unavailable for this engine/version.", 404)
    else:
        profile = None
    with transaction.atomic():
        selection = SlicerMaterialProfilePreference.objects.select_for_update().filter(
            printer=printer, material_key=key, engine=engine, engine_version=version,
        )
        if profile is None:
            selection.delete()
        else:
            SlicerMaterialProfilePreference.objects.update_or_create(
                printer=printer, material_key=key, engine=engine,
                engine_version=version, defaults={"profile": profile},
            )
    return JsonResponse({"slot_id": str(slot.id),
                         "profile_id": str(profile.id) if profile else None})
