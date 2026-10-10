"""Owned reusable spool designs and physical reels.

A reusable reel is hardware; core.Spool continues to represent filament stock.
"""
import json
from decimal import Decimal, InvalidOperation

from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.http import JsonResponse
from django.views.decorators.http import require_http_methods

from .models import Model3D, PrintingLocation, ReusableSpool, ReusableSpoolAssignmentEvent, ReusableSpoolDesign, Spool


def error(message, status=400, fields=None):
    payload = {"error": message}
    if fields:
        payload["fields"] = fields
    return JsonResponse(payload, status=status)


def validation_error(exc):
    return error("Please correct the highlighted fields.", fields=getattr(exc, "message_dict", {"__all__": exc.messages}))


def read_json(request):
    try:
        data = json.loads(request.body.decode("utf-8")) if request.body else {}
        if not isinstance(data, dict):
            raise ValueError()
        return data
    except (ValueError, UnicodeDecodeError):
        raise ValidationError({"__all__": "Send a valid JSON object."})


def permission(request, codename):
    return None if request.user.has_perm("core." + codename) else error("Permission denied.", 403)


def number(payload, field):
    value = payload.get(field)
    if value in (None, ""):
        return None
    try:
        parsed = Decimal(str(value))
        if not parsed.is_finite():
            raise InvalidOperation()
        return parsed
    except (ValueError, TypeError, InvalidOperation):
        raise ValidationError({field: "Enter a valid number."})


def optional_fk(model, owner, raw, field):
    if raw in (None, ""):
        return None
    try:
        item = model.objects.filter(pk=raw, owner=owner).first()
    except (ValueError, ValidationError):
        item = None
    if item is None:
        raise ValidationError({field: "Choose one of your own records."})
    return item


def serialise_design(item):
    return {
        "id": str(item.id), "name": item.name, "manufacturer": item.manufacturer,
        "design_type": item.design_type, "description": item.description,
        "source_url": item.source_url, "material": item.material,
        "nominal_tare_g": str(item.nominal_tare_g) if item.nominal_tare_g is not None else None,
        "max_dryer_temp_c": item.max_dryer_temp_c,
        "temperature_source": item.temperature_source,
        "outer_diameter_mm": str(item.outer_diameter_mm) if item.outer_diameter_mm is not None else None,
        "width_mm": str(item.width_mm) if item.width_mm is not None else None,
        "hub_diameter_mm": str(item.hub_diameter_mm) if item.hub_diameter_mm is not None else None,
        "capacity_g": str(item.capacity_g) if item.capacity_g is not None else None,
        "model_3d_id": str(item.model_3d_id) if item.model_3d_id else None,
    }


def serialise_reel(item):
    return {
        "id": str(item.id), "code": item.code, "design_id": str(item.design_id),
        "design_name": item.design.name, "measured_tare_g": str(item.measured_tare_g) if item.measured_tare_g is not None else None,
        "effective_tare_g": str(item.effective_tare_g) if item.effective_tare_g is not None else None,
        "color_name": item.color_name, "material_override": item.material_override,
        "storage_location_id": str(item.storage_location_id) if item.storage_location_id else None,
        "filament_spool_id": str(item.filament_spool_id) if item.filament_spool_id else None,
        "condition": item.condition,
        "notes": item.notes,
        "assignment_history": [{
            "occurred_at": event.created_at.isoformat(),
            "previous_filament_spool_id": str(event.previous_filament_spool_id) if event.previous_filament_spool_id else None,
            "new_filament_spool_id": str(event.new_filament_spool_id) if event.new_filament_spool_id else None,
            "previous_spool_code": event.previous_spool_code,
            "new_spool_code": event.new_spool_code,
        } for event in item.assignment_events.all()[:20]],
    }


def record_assignment(item, previous_id):
    if previous_id == item.filament_spool_id:
        return
    def code(spool_id):
        return Spool.objects.filter(owner=item.owner, pk=spool_id).values_list("spool_id", flat=True).first() if spool_id else ""
    ReusableSpoolAssignmentEvent.objects.create(
        owner=item.owner,
        reel=item,
        previous_filament_spool_id=previous_id,
        new_filament_spool_id=item.filament_spool_id,
        previous_spool_code=code(previous_id),
        new_spool_code=code(item.filament_spool_id),
    )


def fill_design(item, data):
    for field in ("name", "manufacturer", "design_type", "description", "source_url", "material", "temperature_source"):
        if field in data:
            setattr(item, field, str(data[field] or "").strip())
    for field in ("nominal_tare_g", "outer_diameter_mm", "width_mm", "hub_diameter_mm", "capacity_g"):
        if field in data:
            setattr(item, field, number(data, field))
    if "max_dryer_temp_c" in data:
        value = data["max_dryer_temp_c"]
        try:
            item.max_dryer_temp_c = int(value) if value not in ("", None) else None
        except (ValueError, TypeError):
            raise ValidationError({"max_dryer_temp_c": "Enter a whole-number temperature."})
    if "model_3d_id" in data:
        item.model_3d = optional_fk(Model3D, item.owner, data["model_3d_id"], "model_3d_id")


def fill_reel(item, data):
    for field in ("code", "color_name", "material_override", "condition", "notes"):
        if field in data:
            setattr(item, field, str(data[field] or "").strip())
    if "measured_tare_g" in data:
        item.measured_tare_g = number(data, "measured_tare_g")
    if "design_id" in data:
        item.design = optional_fk(ReusableSpoolDesign, item.owner, data["design_id"], "design_id")
    if "storage_location_id" in data:
        item.storage_location = optional_fk(PrintingLocation, item.owner, data["storage_location_id"], "storage_location_id")
    if "filament_spool_id" in data:
        item.filament_spool = optional_fk(Spool, item.owner, data["filament_spool_id"], "filament_spool_id")


@login_required
@require_http_methods(["GET", "POST"])
def designs(request):
    if request.method == "GET":
        return JsonResponse({"rows": [serialise_design(x) for x in ReusableSpoolDesign.objects.filter(owner=request.user)]})
    denied = permission(request, "add_filamentproduct")
    if denied:
        return denied
    try:
        item = ReusableSpoolDesign(owner=request.user)
        fill_design(item, read_json(request))
        item.full_clean()
        item.save()
        return JsonResponse({"item": serialise_design(item)}, status=201)
    except ValidationError as exc:
        return validation_error(exc)
    except IntegrityError:
        return error("Unable to save the spool design.", 409)


@login_required
@require_http_methods(["PATCH", "DELETE"])
def design_detail(request, design_id):
    item = ReusableSpoolDesign.objects.filter(owner=request.user, pk=design_id).first()
    if item is None:
        return error("Design not found.", 404)
    denied = permission(request, "change_filamentproduct" if request.method == "DELETE" else "change_filamentproduct")
    if denied:
        return denied
    if request.method == "DELETE":
        if item.owned_spools.exists():
            return error("Remove or reassign physical spools before deleting this design.", 409)
        item.delete()
        return JsonResponse({"deleted": True})
    try:
        fill_design(item, read_json(request))
        item.full_clean()
        item.save()
        return JsonResponse({"item": serialise_design(item)})
    except ValidationError as exc:
        return validation_error(exc)


@login_required
@require_http_methods(["GET", "POST"])
def reels(request):
    if request.method == "GET":
        qs = ReusableSpool.objects.filter(owner=request.user).select_related("design").prefetch_related("assignment_events")
        return JsonResponse({"rows": [serialise_reel(x) for x in qs]})
    denied = permission(request, "add_spool")
    if denied:
        return denied
    try:
        item = ReusableSpool(owner=request.user)
        fill_reel(item, read_json(request))
        item.full_clean()
        with transaction.atomic():
            item.save()
            record_assignment(item, None)
        return JsonResponse({"item": serialise_reel(item)}, status=201)
    except ValidationError as exc:
        return validation_error(exc)
    except IntegrityError:
        return error("Spool ID or active filament assignment is already in use.", 409)


@login_required
@require_http_methods(["PATCH", "DELETE"])
def reel_detail(request, reel_id):
    item = ReusableSpool.objects.filter(owner=request.user, pk=reel_id).select_related("design").first()
    if item is None:
        return error("Reusable spool not found.", 404)
    denied = permission(request, "delete_spool" if request.method == "DELETE" else "change_spool")
    if denied:
        return denied
    if request.method == "DELETE":
        item.delete()
        return JsonResponse({"deleted": True})
    try:
        previous_id = item.filament_spool_id
        fill_reel(item, read_json(request))
        item.full_clean()
        with transaction.atomic():
            item.save()
            record_assignment(item, previous_id)
        return JsonResponse({"item": serialise_reel(item)})
    except ValidationError as exc:
        return validation_error(exc)
    except IntegrityError:
        return error("Spool ID or active filament assignment is already in use.", 409)


@login_required
@require_http_methods(["POST", "DELETE"])
def model_design(request, model_id):
    """Quickly mark/unmark a model as a reusable spool design."""
    model = Model3D.objects.filter(owner=request.user, pk=model_id).first()
    if model is None:
        return error("Model not found.", 404)
    denied = permission(request, "add_filamentproduct" if request.method == "POST" else "change_filamentproduct")
    if denied:
        return denied
    design = ReusableSpoolDesign.objects.filter(owner=request.user, model_3d=model).first()
    if request.method == "POST":
        if design is None:
            design = ReusableSpoolDesign(
                owner=request.user, model_3d=model, name=model.name,
                design_type="printed", description=model.description,
                source_url=model.source_url,
            )
            design.full_clean()
            design.save()
        return JsonResponse({"item": serialise_design(design)}, status=200)
    if design is None:
        return JsonResponse({"removed": True})
    if design.owned_spools.exists():
        return error("This model is used by owned reusable spools. Reassign them before unmarking.", 409)
    design.delete()
    return JsonResponse({"removed": True})


# Reference entries deliberately leave tare, dimensions and dryer temperature blank
# until independently verified for the exact spool variant.
KNOWN_REUSABLE_SPOOL_DESIGNS = (
    {
        "key": "bambu-basic",
        "name": "Bambu Reusable Spool (Basic)",
        "manufacturer": "Bambu Lab",
        "design_type": "manufacturer",
        "material": "ABS",
        "nominal_tare_g": "250.00",
        "max_dryer_temp_c": 70,
        "temperature_source": "https://asia.store.bambulab.com/collections/filament-accessories/products/bambu-reusable-spool",
        "description": "Official reusable ABS spool. Manufacturer lists 250 g weight and a 70°C temperature-resistance limit; packing dimensions are not treated as actual spool dimensions.",
        "source_url": "https://asia.store.bambulab.com/collections/filament-accessories/products/bambu-reusable-spool",
    },
    {
        "key": "bambu-high-temp",
        "name": "Bambu Reusable Spool (High Temperature)",
        "manufacturer": "Bambu Lab",
        "design_type": "manufacturer",
        "material": "ABS+PC",
        "nominal_tare_g": "250.00",
        "max_dryer_temp_c": 90,
        "temperature_source": "https://eu.store.bambulab.com/en-at/products/high-temperature-reusable-spool",
        "description": "Official ABS+PC high-temperature reusable spool. Manufacturer lists 250 g weight and a 90°C temperature-resistance limit.",
        "source_url": "https://eu.store.bambulab.com/en-at/products/high-temperature-reusable-spool",
    },
    {
        "key": "prusa-refill-1kg",
        "name": "Prusament Refill 1kg Reusable Spool (Legacy)",
        "manufacturer": "Prusa Research",
        "design_type": "manufacturer",
        "description": "Legacy Prusament spool with removable plastic sides and cardboard centre. Not interchangeable with the newer 900 g refill spool format. Weight and dryer rating unverified.",
        "source_url": "https://help.prusa3d.com/article/how-to-use-prusament-refill-1kg_394630",
    },
    {
        "key": "prusa-refill-900g",
        "name": "Prusament Refill 900g Reusable Spool (New)",
        "manufacturer": "Prusa Research",
        "design_type": "manufacturer",
        "description": "Newer reusable Prusament spool format with a plastic centre and locking sides. Not the legacy 1 kg cardboard-core format; verify exact variant and drying rating.",
        "source_url": "https://help.prusa3d.com/guide/how-to-use-prusament-refill-900g_440297",
    },
    {
        "key": "polymaker-master-printable",
        "name": "Panchroma Master Reusable Spool (Printable)",
        "manufacturer": "Polymaker",
        "design_type": "printed",
        "description": "Printable master spool design linked by Polymaker for its Panchroma PLA refills. Printed weight and temperature tolerance depend on the model, material and slicer settings.",
        "source_url": "https://wiki.polymaker.com/polymaker-products/polymaker-filaments/panchroma-tm/panchroma-tm-pla-refill",
    },
)

@login_required
@require_http_methods(["GET", "POST"])
def manufacturer_catalogue(request):
    if request.method == "GET":
        return JsonResponse({"rows": KNOWN_REUSABLE_SPOOL_DESIGNS})
    denied = permission(request, "add_filamentproduct")
    if denied:
        return denied
    try:
        key = str(read_json(request).get("key") or "")
    except ValidationError as exc:
        return validation_error(exc)
    preset = next((entry for entry in KNOWN_REUSABLE_SPOOL_DESIGNS if entry["key"] == key), None)
    if preset is None:
        return error("Unknown manufacturer spool catalogue entry.", 404)
    item, created = ReusableSpoolDesign.objects.get_or_create(
        owner=request.user,
        name=preset["name"],
        manufacturer=preset["manufacturer"],
        defaults={
            "design_type": preset["design_type"],
            "description": preset["description"],
            "source_url": preset["source_url"],
            "material": preset.get("material", ""),
            "nominal_tare_g": preset.get("nominal_tare_g"),
            "max_dryer_temp_c": preset.get("max_dryer_temp_c"),
            "temperature_source": preset.get("temperature_source", ""),
        },
    )
    return JsonResponse({"item": serialise_design(item), "created": created}, status=201 if created else 200)
