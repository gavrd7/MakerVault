import json
import re
from decimal import Decimal, InvalidOperation

from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.db.models import Q
from django.http import JsonResponse
from django.utils.text import slugify
from django.views.decorators.http import require_http_methods

from .catalogue_images import (
    CatalogueImageError,
    apply_catalogue_image,
    cache_catalogue_image_from_url,
    sanitise_uploaded_image,
)
from .importers import ImporterError, preview_board_url
from .catalogue_enrichment import enrich_board_from_espboards
from .models import (
    BoardCompatibility,
    BoardModel,
    CatalogSource,
    ComponentCategory,
    ComponentModel,
    FilamentProduct,
    InventoryItem,
    InventoryHistory,
    Manufacturer,
    Model3D,
    Printer,
    Project,
    Spool,
)


def _error(message, status=400, fields=None):
    payload = {"error": message}
    if fields:
        payload["fields"] = fields
    return JsonResponse(payload, status=status)


def _read_json(request):
    try:
        if not request.body:
            return {}
        return json.loads(request.body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("Request body must be valid JSON.") from exc


def _validation_response(exc):
    if hasattr(exc, "message_dict"):
        fields = {key: [str(item) for item in value] for key, value in exc.message_dict.items()}
        return _error("Please correct the highlighted fields.", fields=fields)
    return _error("; ".join(str(item) for item in exc.messages))


def _require_permission(request, codename):
    if request.user.has_perm(codename):
        return None
    return _error("You do not have permission to perform this action.", status=403)


def _float(value):
    return float(value) if value is not None else None


def _image_url(obj):
    if getattr(obj, "image", None):
        try:
            return obj.image.url
        except ValueError:
            pass
    specs = getattr(obj, "specifications", {}) or {}
    return specs.get("external_image_url") or ""


def _serialise_board(board, detailed=False):
    compatibility = [
        {
            "platform": item.platform,
            "support_level": item.support_level,
            "support_label": item.get_support_level_display(),
            "notes": item.notes,
            "source_url": item.source_url,
        }
        for item in board.compatibility.all()
    ]
    data = {
        "id": str(board.id),
        "name": board.name,
        "display_name": str(board),
        "manufacturer": board.manufacturer.name if board.manufacturer else "Generic",
        "manufacturer_id": board.manufacturer_id,
        "family": board.family,
        "variant": board.variant,
        "mcu": board.mcu,
        "architecture": board.architecture,
        "flash_mb": _float(board.flash_mb),
        "psram_mb": _float(board.psram_mb),
        "ram_kb": _float(board.ram_kb),
        "gpio_count": board.gpio_count,
        "wifi": board.wifi,
        "bluetooth": board.bluetooth,
        "zigbee": board.zigbee,
        "thread": board.thread,
        "usb_connector": board.usb_connector,
        "image": _image_url(board),
        "image_cached": bool(board.image),
        "image_source_url": (board.specifications or {}).get("image_source_url") or (board.specifications or {}).get("external_image_url") or "",
        "image_source_page": (board.specifications or {}).get("image_source_page") or "",
        "image_source_provider": (board.specifications or {}).get("image_source_provider") or "",
        "image_license": (board.specifications or {}).get("image_license") or "",
        "image_author": (board.specifications or {}).get("image_author") or "",
        "source": board.source.name if board.source else "Manual",
        "source_url": board.source.url if board.source else "",
        "compatibility": compatibility,
        "updated_at": board.updated_at.isoformat(),
    }
    if detailed:
        data.update({
            "description": board.description,
            "dimensions_mm": board.dimensions_mm,
            "specifications": board.specifications,
            "pinout": board.pinout,
        })
    return data


def _serialise_component(component):
    specs = component.specifications or {}
    return {
        "id": str(component.id),
        "name": component.name,
        "manufacturer": component.manufacturer.name if component.manufacturer else "Generic",
        "category": component.category.name if component.category else "Uncategorised",
        "category_id": component.category_id,
        "part_number": component.part_number,
        "description": component.description,
        "image": _image_url(component),
        "image_cached": bool(component.image),
        "image_source_url": specs.get("image_source_url") or specs.get("external_image_url") or "",
        "image_source_page": specs.get("image_source_page") or "",
        "image_source_provider": specs.get("image_source_provider") or "",
        "image_license": specs.get("image_license") or "",
        "image_author": specs.get("image_author") or "",
        "specifications": specs,
        "type": specs.get("type", ""),
        "interface": specs.get("interface", ""),
        "voltage": specs.get("voltage") or specs.get("input") or "",
        "package": specs.get("package", ""),
        "source": component.source.name if component.source else "Manual",
        "source_url": component.source.url if component.source else "",
        "updated_at": component.updated_at.isoformat(),
    }


def _serialise_inventory(item):
    image_url = ""
    if item.image:
        try:
            image_url = item.image.url
        except ValueError:
            image_url = ""
    if not image_url and item.board:
        image_url = _image_url(item.board)
    if not image_url and item.component:
        image_url = _image_url(item.component)
    return {
        "id": str(item.id),
        "inventory_id": item.inventory_id,
        "item_type": item.item_type,
        "type": item.get_item_type_display(),
        "name": item.display_name,
        "custom_name": item.custom_name,
        "board_id": str(item.board_id) if item.board_id else "",
        "component_id": str(item.component_id) if item.component_id else "",
        "quantity": _float(item.quantity),
        "status": item.status,
        "status_label": item.get_status_display(),
        "project_id": str(item.project_id) if item.project_id else "",
        "project": item.project.name if item.project else "",
        "location": item.location,
        "serial_number": item.serial_number,
        "purchase_price": _float(item.purchase_price),
        "currency": item.currency,
        "supplier": item.supplier,
        "purchase_url": item.purchase_url,
        "purchased_on": item.purchased_on.isoformat() if item.purchased_on else "",
        "notes": item.notes,
        "image": image_url,
        "updated_at": item.updated_at.isoformat(),
    }



def _serialise_inventory_history(entry):
    return {
        "id": str(entry.id),
        "event_type": entry.event_type,
        "event_label": entry.get_event_type_display(),
        "summary": entry.summary,
        "changes": entry.changes,
        "project_id": str(entry.project_id) if entry.project_id else "",
        "project": entry.project.name if entry.project else "",
        "changed_by": entry.changed_by.get_username() if entry.changed_by else "",
        "created_at": entry.created_at.isoformat(),
    }


def _inventory_snapshot(item):
    return {
        "quantity": str(item.quantity),
        "status": item.status,
        "project_id": str(item.project_id) if item.project_id else "",
        "project": item.project.name if item.project else "",
        "location": item.location,
        "serial_number": item.serial_number,
        "purchase_price": str(item.purchase_price) if item.purchase_price is not None else "",
        "currency": item.currency,
        "supplier": item.supplier,
        "purchase_url": item.purchase_url,
        "purchased_on": item.purchased_on.isoformat() if item.purchased_on else "",
        "notes": item.notes,
        "custom_name": item.custom_name,
    }


def _record_inventory_history(item, user, before=None, *, created=False):
    after = _inventory_snapshot(item)
    if created:
        InventoryHistory.objects.create(
            inventory_item=item,
            event_type="created",
            summary=f"Added {item.display_name} to inventory",
            changes={"after": after},
            project=item.project,
            changed_by=user,
        )
        return

    before = before or {}
    changes = {}
    for key, new_value in after.items():
        old_value = before.get(key, "")
        if old_value != new_value:
            changes[key] = {"from": old_value, "to": new_value}
    if not changes:
        return

    if "project_id" in changes:
        if item.project:
            event_type = "assigned"
            summary = f"Assigned to project {item.project.name}"
        else:
            event_type = "unassigned"
            previous = changes.get("project", {}).get("from") or "project"
            summary = f"Removed from project {previous}"
    elif "status" in changes:
        event_type = "status"
        summary = f"Status changed to {item.get_status_display()}"
    elif "location" in changes:
        event_type = "location"
        summary = f"Location changed to {item.location or 'Unspecified'}"
    else:
        event_type = "updated"
        labels = {
            "quantity": "quantity", "serial_number": "serial number",
            "purchase_price": "purchase price", "currency": "currency",
            "supplier": "supplier", "purchase_url": "purchase URL",
            "purchased_on": "purchase date", "notes": "notes",
            "custom_name": "name",
        }
        changed = [labels.get(key, key.replace("_", " ")) for key in changes]
        summary = "Updated " + ", ".join(changed[:3])
        if len(changed) > 3:
            summary += f" and {len(changed) - 3} more"

    InventoryHistory.objects.create(
        inventory_item=item,
        event_type=event_type,
        summary=summary[:500],
        changes=changes,
        project=item.project,
        changed_by=user,
    )


def _parse_decimal(value, field_name, allow_none=True):
    if value in (None, "") and allow_none:
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise ValidationError({field_name: "Enter a valid number."}) from exc


def _next_inventory_id(item_type):
    prefix = {
        "board": "MCU",
        "component": "CMP",
        "tool": "AST",
        "printed_part": "PRT",
        "other": "OTH",
    }.get(item_type, "INV")
    highest = 0
    for existing in InventoryItem.objects.filter(inventory_id__startswith=f"{prefix}-").values_list("inventory_id", flat=True):
        match = re.fullmatch(rf"{re.escape(prefix)}-(\d+)", existing or "")
        if match:
            highest = max(highest, int(match.group(1)))
    candidate = highest + 1
    while InventoryItem.objects.filter(inventory_id=f"{prefix}-{candidate:04d}").exists():
        candidate += 1
    return f"{prefix}-{candidate:04d}"


@login_required
@require_http_methods(["GET"])
def dashboard(request):
    data = {
        "inventory_total": InventoryItem.objects.count(),
        "inventory_available": InventoryItem.objects.filter(status="available").count(),
        "inventory_in_use": InventoryItem.objects.filter(status="in_use").count(),
        "projects_active": Project.objects.filter(status="active").count(),
        "projects_total": Project.objects.count(),
        "board_models": BoardModel.objects.count(),
        "component_models": ComponentModel.objects.count(),
        "filament_products": FilamentProduct.objects.count(),
        "spools": Spool.objects.count(),
        "printers": Printer.objects.count(),
        "models_3d": Model3D.objects.count(),
    }
    return JsonResponse(data)


@login_required
@require_http_methods(["GET", "POST"])
def inventory(request):
    if request.method == "GET":
        qs = InventoryItem.objects.select_related(
            "board__manufacturer", "component__manufacturer", "project"
        ).all()[:5000]
        return JsonResponse({"rows": [_serialise_inventory(item) for item in qs]})

    denied = _require_permission(request, "core.add_inventoryitem")
    if denied:
        return denied
    try:
        payload = _read_json(request)
        item_type = str(payload.get("item_type") or "board")
        if item_type not in dict(InventoryItem.ITEM_TYPES):
            return _error("Unknown inventory item type.")

        board = None
        component = None
        if payload.get("board_id"):
            board = BoardModel.objects.filter(pk=payload["board_id"]).first()
            if not board:
                return _error("Selected board was not found.")
        if payload.get("component_id"):
            component = ComponentModel.objects.filter(pk=payload["component_id"]).first()
            if not component:
                return _error("Selected component was not found.")

        project = None
        if payload.get("project_id"):
            project = Project.objects.filter(pk=payload["project_id"]).first()
            if not project:
                return _error("Selected project was not found.")

        with transaction.atomic():
            item = InventoryItem(
                inventory_id=(str(payload.get("inventory_id") or "").strip() or _next_inventory_id(item_type)),
                item_type=item_type,
                board=board,
                component=component,
                custom_name=str(payload.get("custom_name") or "").strip(),
                quantity=_parse_decimal(payload.get("quantity", 1), "quantity", allow_none=False),
                status=str(payload.get("status") or "available"),
                project=project,
                location=str(payload.get("location") or "").strip(),
                serial_number=str(payload.get("serial_number") or "").strip(),
                purchase_price=_parse_decimal(payload.get("purchase_price"), "purchase_price"),
                currency=str(payload.get("currency") or settings.MAKERVAULT_CURRENCY).upper()[:3],
                supplier=str(payload.get("supplier") or "").strip(),
                purchase_url=str(payload.get("purchase_url") or "").strip(),
                notes=str(payload.get("notes") or "").strip(),
            )
            item.full_clean()
            item.save()
            _record_inventory_history(item, request.user, created=True)
        return JsonResponse({"item": _serialise_inventory(item)}, status=201)
    except ValidationError as exc:
        return _validation_response(exc)
    except (ValueError, IntegrityError) as exc:
        return _error(str(exc))


@login_required
@require_http_methods(["GET", "PATCH", "DELETE"])
def inventory_detail(request, item_id):
    item = InventoryItem.objects.select_related(
        "board__manufacturer", "board__source", "component__manufacturer",
        "component__category", "component__source", "project"
    ).filter(pk=item_id).first()
    if not item:
        return _error("Inventory item not found.", status=404)

    if request.method == "GET":
        history = item.history.select_related("project", "changed_by").all()[:250]
        payload = _serialise_inventory(item)
        payload["board"] = _serialise_board(item.board, detailed=True) if item.board else None
        payload["component"] = _serialise_component(item.component) if item.component else None
        payload["history"] = [_serialise_inventory_history(entry) for entry in history]
        return JsonResponse({"item": payload})

    if request.method == "DELETE":
        denied = _require_permission(request, "core.delete_inventoryitem")
        if denied:
            return denied
        item.delete()
        return JsonResponse({"deleted": True})

    denied = _require_permission(request, "core.change_inventoryitem")
    if denied:
        return denied
    try:
        before = _inventory_snapshot(item)
        payload = _read_json(request)
        simple_fields = {
            "location", "serial_number", "supplier", "purchase_url", "notes", "custom_name"
        }
        for field in simple_fields:
            if field in payload:
                setattr(item, field, str(payload[field] or "").strip())

        if "quantity" in payload:
            item.quantity = _parse_decimal(payload["quantity"], "quantity", allow_none=False)
        if "purchase_price" in payload:
            item.purchase_price = _parse_decimal(payload["purchase_price"], "purchase_price")
        if "currency" in payload:
            item.currency = str(payload["currency"] or settings.MAKERVAULT_CURRENCY).upper()[:3]
        if "status" in payload:
            item.status = str(payload["status"])
        if "purchased_on" in payload:
            raw_date = str(payload["purchased_on"] or "").strip()
            if raw_date:
                from datetime import date
                try:
                    item.purchased_on = date.fromisoformat(raw_date)
                except ValueError as exc:
                    raise ValidationError({"purchased_on": "Enter a valid date."}) from exc
            else:
                item.purchased_on = None
        if "project_id" in payload:
            if payload["project_id"]:
                project = Project.objects.filter(pk=payload["project_id"]).first()
                if not project:
                    return _error("Selected project was not found.")
                item.project = project
            else:
                item.project = None

        item.full_clean()
        item.save()
        _record_inventory_history(item, request.user, before)
        item = InventoryItem.objects.select_related(
            "board__manufacturer", "component__manufacturer", "project"
        ).get(pk=item.pk)
        return JsonResponse({"item": _serialise_inventory(item)})
    except ValidationError as exc:
        return _validation_response(exc)
    except ValueError as exc:
        return _error(str(exc))


@login_required
@require_http_methods(["GET", "POST"])
def boards(request):
    if request.method == "GET":
        qs = BoardModel.objects.select_related("manufacturer", "source").prefetch_related("compatibility")
        query = request.GET.get("q", "").strip()
        manufacturer = request.GET.get("manufacturer", "").strip()
        family = request.GET.get("family", "").strip()
        if query:
            qs = qs.filter(
                Q(name__icontains=query)
                | Q(manufacturer__name__icontains=query)
                | Q(family__icontains=query)
                | Q(mcu__icontains=query)
                | Q(variant__icontains=query)
            )
        if manufacturer:
            qs = qs.filter(manufacturer__name=manufacturer)
        if family:
            qs = qs.filter(family=family)
        rows = [_serialise_board(board) for board in qs[:5000]]
        manufacturers = list(
            Manufacturer.objects.filter(boards__isnull=False).distinct().order_by("name").values_list("name", flat=True)
        )
        families = list(
            BoardModel.objects.exclude(family="").order_by("family").values_list("family", flat=True).distinct()
        )
        return JsonResponse({"rows": rows, "manufacturers": manufacturers, "families": families})

    denied = _require_permission(request, "core.add_boardmodel")
    if denied:
        return denied
    try:
        payload = _read_json(request)
        name = str(payload.get("name") or "").strip()
        if not name:
            return _error("Board name is required.", fields={"name": ["This field is required."]})
        manufacturer_name = str(payload.get("manufacturer") or "Generic").strip() or "Generic"
        manufacturer, _ = Manufacturer.objects.get_or_create(name=manufacturer_name)
        board = BoardModel(
            manufacturer=manufacturer,
            name=name,
            family=str(payload.get("family") or "").strip(),
            variant=str(payload.get("variant") or "").strip(),
            description=str(payload.get("description") or "").strip(),
            mcu=str(payload.get("mcu") or "").strip(),
            architecture=str(payload.get("architecture") or "").strip(),
            flash_mb=_parse_decimal(payload.get("flash_mb"), "flash_mb"),
            psram_mb=_parse_decimal(payload.get("psram_mb"), "psram_mb"),
            ram_kb=_parse_decimal(payload.get("ram_kb"), "ram_kb"),
            gpio_count=int(payload["gpio_count"]) if payload.get("gpio_count") not in (None, "") else None,
            wifi=bool(payload.get("wifi", False)),
            bluetooth=bool(payload.get("bluetooth", False)),
            zigbee=bool(payload.get("zigbee", False)),
            thread=bool(payload.get("thread", False)),
            usb_connector=str(payload.get("usb_connector") or "").strip(),
        )
        board.full_clean()
        board.save()
        for platform in payload.get("compatibility", []):
            if isinstance(platform, str) and platform.strip():
                BoardCompatibility.objects.get_or_create(
                    board=board,
                    platform=platform.strip(),
                    defaults={"support_level": "unknown"},
                )
        board = BoardModel.objects.select_related("manufacturer", "source").prefetch_related("compatibility").get(pk=board.pk)
        return JsonResponse({"board": _serialise_board(board, detailed=True)}, status=201)
    except ValidationError as exc:
        return _validation_response(exc)
    except (ValueError, IntegrityError) as exc:
        return _error(str(exc))


@login_required
@require_http_methods(["GET"])
def board_detail(request, board_id):
    board = BoardModel.objects.select_related("manufacturer", "source").prefetch_related("compatibility").filter(pk=board_id).first()
    if not board:
        return _error("Board not found.", status=404)
    return JsonResponse({"board": _serialise_board(board, detailed=True)})


@login_required
@require_http_methods(["POST"])
def board_enrich(request, board_id):
    denied = _require_permission(request, "core.change_boardmodel")
    if denied:
        return denied
    board = BoardModel.objects.select_related("manufacturer", "source").prefetch_related("compatibility").filter(pk=board_id).first()
    if not board:
        return _error("Board not found.", status=404)
    try:
        changed = enrich_board_from_espboards(board)
    except Exception as exc:
        return _error(f"Board enrichment failed: {exc}")
    board = BoardModel.objects.select_related("manufacturer", "source").prefetch_related("compatibility").get(pk=board.pk)
    return JsonResponse({"board": _serialise_board(board, detailed=True), "changed": changed})


@login_required
@require_http_methods(["GET", "POST"])
def components(request):
    if request.method == "GET":
        qs = ComponentModel.objects.select_related("manufacturer", "category", "source")
        query = request.GET.get("q", "").strip()
        if query:
            qs = qs.filter(
                Q(name__icontains=query)
                | Q(manufacturer__name__icontains=query)
                | Q(category__name__icontains=query)
                | Q(part_number__icontains=query)
            )
        rows = [_serialise_component(item) for item in qs[:5000]]
        categories = list(ComponentCategory.objects.order_by("name").values_list("name", flat=True))
        return JsonResponse({"rows": rows, "categories": categories})

    denied = _require_permission(request, "core.add_componentmodel")
    if denied:
        return denied
    try:
        payload = _read_json(request)
        name = str(payload.get("name") or "").strip()
        if not name:
            return _error("Component name is required.")
        manufacturer_name = str(payload.get("manufacturer") or "Generic").strip() or "Generic"
        manufacturer, _ = Manufacturer.objects.get_or_create(name=manufacturer_name)
        category = None
        category_name = str(payload.get("category") or "").strip()
        if category_name:
            category, _ = ComponentCategory.objects.get_or_create(
                slug=slugify(category_name)[:140], defaults={"name": category_name}
            )
        specifications = payload.get("specifications") or {}
        if not isinstance(specifications, dict):
            return _error("Component specifications must be an object.")
        component = ComponentModel(
            manufacturer=manufacturer,
            category=category,
            name=name,
            part_number=str(payload.get("part_number") or "").strip(),
            description=str(payload.get("description") or "").strip(),
            specifications=specifications,
        )
        component.full_clean()
        component.save()
        return JsonResponse({"component": _serialise_component(component)}, status=201)
    except ValidationError as exc:
        return _validation_response(exc)
    except (ValueError, IntegrityError) as exc:
        return _error(str(exc))



@login_required
@require_http_methods(["GET"])
def component_detail(request, component_id):
    component = ComponentModel.objects.select_related("manufacturer", "category", "source").filter(pk=component_id).first()
    if not component:
        return _error("Component not found.", status=404)
    return JsonResponse({"component": _serialise_component(component)})


def _catalogue_image_response(request, obj, permission, serializer, response_key):
    denied = _require_permission(request, permission)
    if denied:
        return denied

    if request.method == "DELETE":
        if obj.image:
            obj.image.delete(save=False)
        specs = dict(obj.specifications or {})
        for key in [
            "external_image_url", "image_source_url", "image_source_type", "image_cached_at",
            "image_source_provider", "image_source_page", "image_source_query",
            "image_license", "image_author", "auto_image_seeded", "auto_image_seeded_at",
        ]:
            specs.pop(key, None)
        # A deliberate removal is respected by the automatic seeder.
        specs["auto_image_opt_out"] = True
        obj.specifications = specs
        obj.image = None
        obj.save()
        return JsonResponse({response_key: serializer(obj)})

    try:
        if request.FILES.get("image"):
            uploaded = request.FILES["image"]
            stem = getattr(obj, "slug", "") or getattr(obj, "name", "") or str(obj.pk)
            image_content, filename = sanitise_uploaded_image(uploaded, stem)
            apply_catalogue_image(obj, image_content, filename, source_type="upload")
        else:
            payload = _read_json(request)
            image_url = str(payload.get("url") or "").strip()
            if not image_url:
                return _error("Choose an image file or enter an HTTPS image URL.")
            cache_catalogue_image_from_url(obj, image_url)
        return JsonResponse({response_key: serializer(obj)})
    except CatalogueImageError as exc:
        return _error(str(exc))


@login_required
@require_http_methods(["POST", "DELETE"])
def board_image(request, board_id):
    board = BoardModel.objects.select_related("manufacturer", "source").prefetch_related("compatibility").filter(pk=board_id).first()
    if not board:
        return _error("Board not found.", status=404)
    return _catalogue_image_response(
        request, board, "core.change_boardmodel",
        lambda item: _serialise_board(item, detailed=True), "board",
    )


@login_required
@require_http_methods(["POST", "DELETE"])
def component_image(request, component_id):
    component = ComponentModel.objects.select_related("manufacturer", "category", "source").filter(pk=component_id).first()
    if not component:
        return _error("Component not found.", status=404)
    return _catalogue_image_response(
        request, component, "core.change_componentmodel",
        _serialise_component, "component",
    )


@login_required
@require_http_methods(["GET"])
def projects_lookup(request):
    rows = [
        {"id": str(project.id), "name": project.name, "status": project.status, "status_label": project.get_status_display()}
        for project in Project.objects.order_by("name")
    ]
    return JsonResponse({"rows": rows})


@login_required
@require_http_methods(["POST"])
def import_board_preview(request):
    denied = _require_permission(request, "core.add_boardmodel")
    if denied:
        return denied
    try:
        payload = _read_json(request)
        data = preview_board_url(str(payload.get("url") or ""))
        return JsonResponse({"preview": data})
    except (ValueError, ImporterError) as exc:
        return _error(str(exc))


@login_required
@require_http_methods(["POST"])
def import_board_commit(request):
    denied = _require_permission(request, "core.add_boardmodel")
    if denied:
        return denied
    try:
        payload = _read_json(request)
        data = preview_board_url(str(payload.get("url") or ""))
        manufacturer, _ = Manufacturer.objects.get_or_create(name=data["manufacturer"] or "Generic")
        source, _ = CatalogSource.objects.update_or_create(
            source_type=data["source_type"],
            url=data["source_url"],
            defaults={
                "name": f"{data['source_name']} — {data['name']}",
                "external_id": data["source_url"].rstrip("/").split("/")[-1],
                "raw_metadata": data,
            },
        )
        defaults = {
            "source": source,
            "description": data["description"],
            "family": data["family"],
            "mcu": data["mcu"],
            "architecture": data["architecture"],
            "flash_mb": data["flash_mb"],
            "psram_mb": data["psram_mb"],
            "ram_kb": data["ram_kb"],
            "gpio_count": data["gpio_count"],
            "wifi": data["wifi"],
            "bluetooth": data["bluetooth"],
            "zigbee": data["zigbee"],
            "thread": data["thread"],
            "usb_connector": data["usb_connector"],
            "dimensions_mm": data["dimensions_mm"],
            "specifications": data["specifications"],
        }
        board, created = BoardModel.objects.get_or_create(
            manufacturer=manufacturer,
            name=data["name"],
            variant=data.get("variant", ""),
            defaults=defaults,
        )
        if not created:
            changed = False
            if not board.source or (
                board.source.source_type == "manual"
                and board.source.name == "MakerVault starter catalogue"
            ):
                board.source = source
                changed = True
            for field in ["description", "family", "mcu", "architecture", "usb_connector"]:
                if not getattr(board, field) and defaults[field]:
                    setattr(board, field, defaults[field])
                    changed = True
            for field in ["flash_mb", "psram_mb", "ram_kb", "gpio_count"]:
                if getattr(board, field) is None and defaults[field] is not None:
                    setattr(board, field, defaults[field])
                    changed = True
            for field in ["wifi", "bluetooth", "zigbee", "thread"]:
                new_value = bool(getattr(board, field) or defaults[field])
                if new_value != getattr(board, field):
                    setattr(board, field, new_value)
                    changed = True
            if not board.dimensions_mm and defaults["dimensions_mm"]:
                board.dimensions_mm = defaults["dimensions_mm"]
                changed = True
            merged_specs = {**(defaults["specifications"] or {}), **(board.specifications or {})}
            if merged_specs != board.specifications:
                board.specifications = merged_specs
                changed = True
            if changed:
                board.full_clean()
                board.save()

        for compat in data.get("compatibility", []):
            existing, was_created = BoardCompatibility.objects.get_or_create(
                board=board,
                platform=compat["platform"],
                defaults={"support_level": compat.get("support_level", "unknown"), "source_url": data["source_url"]},
            )
            if not was_created and existing.support_level == "unknown" and compat.get("support_level"):
                existing.support_level = compat["support_level"]
                existing.source_url = existing.source_url or data["source_url"]
                existing.save(update_fields=["support_level", "source_url", "updated_at"])

        if data.get("image_url") and not board.image:
            try:
                cache_catalogue_image_from_url(board, data["image_url"])
            except CatalogueImageError:
                # The catalogue record remains useful even when a remote image
                # cannot be cached; the source URL is retained in specifications.
                pass

        board = BoardModel.objects.select_related("manufacturer", "source").prefetch_related("compatibility").get(pk=board.pk)
        return JsonResponse({"board": _serialise_board(board, detailed=True), "created": created})
    except (ValueError, ImporterError) as exc:
        return _error(str(exc))
    except ValidationError as exc:
        return _validation_response(exc)


def _attribution_row(kind, obj):
    specs = obj.specifications or {}
    provider = specs.get("image_source_provider") or ""
    page = specs.get("image_source_page") or ""
    image_url = specs.get("image_source_url") or specs.get("external_image_url") or ""
    if not (provider or page or image_url):
        return None
    return {
        "kind": kind,
        "id": str(obj.id),
        "name": str(obj),
        "provider": provider or "External source",
        "author": specs.get("image_author") or "",
        "license": specs.get("image_license") or "",
        "source_page": page or image_url,
        "cached": bool(obj.image),
    }


@login_required
@require_http_methods(["GET"])
def attributions(request):
    rows = []
    for board in BoardModel.objects.select_related("manufacturer").exclude(specifications={}):
        row = _attribution_row("Board", board)
        if row:
            rows.append(row)
    for component in ComponentModel.objects.select_related("manufacturer", "category").exclude(specifications={}):
        row = _attribution_row("Component", component)
        if row:
            rows.append(row)
    rows.sort(key=lambda row: (row["provider"].lower(), row["name"].lower()))
    return JsonResponse({
        "rows": rows,
        "summary": {
            "total": len(rows),
            "with_license": sum(1 for row in rows if row["license"]),
            "needs_review": sum(1 for row in rows if not row["license"]),
        },
    })


@login_required
@require_http_methods(["GET"])
def public_config(request):
    return JsonResponse({
        "version": settings.MAKERVAULT_VERSION,
        "license": settings.MAKERVAULT_LICENSE,
        "source_url": settings.MAKERVAULT_SOURCE_URL,
        "license_url": "/legal/license/",
        "third_party_notices_url": "/legal/third-party-notices/",
        "currency": settings.MAKERVAULT_CURRENCY,
        "measurement_system": settings.MAKERVAULT_MEASUREMENT_SYSTEM,
        "timezone": settings.TIME_ZONE,
        "language": settings.LANGUAGE_CODE,
        "user": request.user.get_username(),
        "is_staff": request.user.is_staff,
        "permissions": {
            "add_board": request.user.has_perm("core.add_boardmodel"),
            "change_board": request.user.has_perm("core.change_boardmodel"),
            "add_component": request.user.has_perm("core.add_componentmodel"),
            "change_component": request.user.has_perm("core.change_componentmodel"),
            "add_inventory": request.user.has_perm("core.add_inventoryitem"),
            "change_inventory": request.user.has_perm("core.change_inventoryitem"),
            "delete_inventory": request.user.has_perm("core.delete_inventoryitem"),
        },
        "importers": ["ESPBoards.dev"],
    })
