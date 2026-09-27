import hashlib
import json
import re
from pathlib import Path
from datetime import timedelta
from decimal import Decimal, InvalidOperation

from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.db.models import Count, Q, Sum
from django.db.models.deletion import ProtectedError
from django.http import JsonResponse
from django.utils import timezone
from django.utils.text import slugify
from django.views.decorators.http import require_http_methods

from .catalogue_images import (
    CatalogueImageError,
    apply_catalogue_image,
    cache_catalogue_image_from_url,
    sanitise_uploaded_image,
)
from .importers import ImporterError, preview_board_url
from .catalogue_enrichment import enrich_board
from .filament_catalogue import (
    FilamentCatalogueError,
    get_spoolmandb_item,
    search_spoolmandb,
    spoolmandb_meta,
)
from .printing_catalogue_seed import COMMON_FILAMENT_MATERIALS
from .printing_integrations import PrintingIntegrationError, probe_spoolman
from .tasks import queue_catalogue_maintenance_now
from .models import (
    BoardCompatibility,
    BoardModel,
    BOMAllocation,
    BOMItem,
    CatalogSource,
    CatalogueMaintenanceSettings,
    ComponentCategory,
    ComponentModel,
    FilamentManufacturer,
    FilamentProduct,
    FileAsset,
    InventoryItem,
    InventoryHistory,
    Manufacturer,
    Model3D,
    ModelRevision,
    ModelRevisionAsset,
    Printer,
    PrinterCatalogModel,
    PrinterFilamentSlot,
    PrinterManufacturer,
    PrintingIntegrationSetting,
    PrintingLocation,
    PrintJob,
    PrintMaterialUsage,
    Project,
    RepositoryLink,
    Spool,
    ExternalSpoolLink,
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


def _inventory_allocated_quantity(item):
    allocated = getattr(item, "allocated_quantity", None)
    if allocated is None:
        allocated = item.bom_allocations.aggregate(total=Sum("quantity"))["total"]
    return allocated or Decimal("0")


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
    allocated = _inventory_allocated_quantity(item)
    available = max((item.quantity or Decimal("0")) - allocated, Decimal("0"))
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
        "allocated_quantity": _float(allocated),
        "available_quantity": _float(available),
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



def _record_bom_allocation_history(allocation, user, event_type, *, previous_quantity=None):
    inventory = allocation.inventory_item
    bom_item = allocation.bom_item
    if event_type == "bom_released":
        summary = f"Released {allocation.quantity} from BOM: {bom_item.display_name}"
    elif previous_quantity is not None:
        summary = f"Changed BOM allocation for {bom_item.display_name}: {previous_quantity} → {allocation.quantity}"
    else:
        summary = f"Allocated {allocation.quantity} to BOM: {bom_item.display_name}"
    InventoryHistory.objects.create(
        inventory_item=inventory,
        event_type=event_type,
        summary=summary[:500],
        changes={
            "bom_item_id": bom_item.pk,
            "bom_item": bom_item.display_name,
            "quantity": str(allocation.quantity),
            "previous_quantity": str(previous_quantity) if previous_quantity is not None else "",
        },
        project=bom_item.project,
        changed_by=user,
    )


def _serialise_bom_allocation(allocation):
    inventory = allocation.inventory_item
    inventory_allocated = _inventory_allocated_quantity(inventory)
    inventory_available = max(
        (inventory.quantity or Decimal("0")) - inventory_allocated,
        Decimal("0"),
    )
    return {
        "id": allocation.pk,
        "inventory_item_id": str(inventory.pk),
        "inventory_id": inventory.inventory_id,
        "inventory_name": inventory.display_name,
        "inventory_image": _serialise_inventory(inventory).get("image", ""),
        "quantity": _float(allocation.quantity),
        "inventory_total_quantity": _float(inventory.quantity),
        "inventory_available_quantity": _float(inventory_available),
        "status": inventory.status,
        "status_label": inventory.get_status_display(),
        "location": inventory.location,
        "notes": allocation.notes,
        "allocated_by": allocation.allocated_by.get_username() if allocation.allocated_by else "",
        "created_at": allocation.created_at.isoformat(),
        "updated_at": allocation.updated_at.isoformat(),
    }


def _serialise_bom_item(item):
    allocations = list(item.allocations.select_related(
        "inventory_item__board__manufacturer",
        "inventory_item__component__manufacturer",
        "allocated_by",
    ).all())
    allocated = sum((allocation.quantity for allocation in allocations), Decimal("0"))
    required = item.quantity or Decimal("0")
    remaining = max(required - allocated, Decimal("0"))
    if allocated <= 0:
        allocation_status = "unallocated"
    elif remaining > 0:
        allocation_status = "partial"
    else:
        allocation_status = "complete"
    estimated_cost = (
        item.unit_cost * required
        if item.unit_cost is not None else None
    )
    source_type = "board" if item.board_id else "component" if item.component_id else "custom"
    return {
        "id": item.pk,
        "name": item.display_name,
        "custom_name": item.custom_name,
        "source_type": source_type,
        "board_id": str(item.board_id) if item.board_id else "",
        "board": str(item.board) if item.board else "",
        "component_id": str(item.component_id) if item.component_id else "",
        "component": str(item.component) if item.component else "",
        "quantity": _float(required),
        "unit": item.unit,
        "unit_cost": _float(item.unit_cost),
        "estimated_cost": _float(estimated_cost),
        "currency": item.currency,
        "notes": item.notes,
        "allocated_quantity": _float(allocated),
        "remaining_quantity": _float(remaining),
        "allocation_status": allocation_status,
        "allocations": [_serialise_bom_allocation(allocation) for allocation in allocations],
        "created_at": item.created_at.isoformat(),
        "updated_at": item.updated_at.isoformat(),
    }


def _project_bom(project):
    items = list(project.bom_items.select_related(
        "board__manufacturer", "component__manufacturer"
    ).prefetch_related(
        "allocations__inventory_item__board__manufacturer",
        "allocations__inventory_item__component__manufacturer",
        "allocations__allocated_by",
    ).all())
    rows = [_serialise_bom_item(item) for item in items]
    complete = sum(1 for item in rows if item["allocation_status"] == "complete")
    costs = [item for item in rows if item["estimated_cost"] is not None]
    currencies = {item["currency"] for item in costs}
    estimated_cost = sum((Decimal(str(item["estimated_cost"])) for item in costs), Decimal("0")) if len(currencies) <= 1 else None
    return rows, {
        "line_count": len(rows),
        "complete_lines": complete,
        "partial_lines": sum(1 for item in rows if item["allocation_status"] == "partial"),
        "unallocated_lines": sum(1 for item in rows if item["allocation_status"] == "unallocated"),
        "estimated_cost": _float(estimated_cost),
        "currency": next(iter(currencies), settings.MAKERVAULT_CURRENCY),
        "mixed_currency": len(currencies) > 1,
    }


def _file_url(field):
    if not field:
        return ""
    try:
        return field.url
    except ValueError:
        return ""


def _serialise_file_asset(asset):
    metadata = asset.metadata or {}
    try:
        size_bytes = asset.file.size if asset.file else 0
    except (OSError, ValueError):
        size_bytes = metadata.get("size_bytes") or 0
    filename = metadata.get("original_name") or (Path(asset.file.name).name if asset.file else "")
    return {
        "id": str(asset.id),
        "name": asset.name,
        "category": asset.category,
        "category_label": asset.get_category_display(),
        "url": _file_url(asset.file),
        "filename": filename,
        "version": asset.version,
        "description": asset.description,
        "sha256": asset.sha256,
        "size_bytes": size_bytes,
        "project_id": str(asset.project_id) if asset.project_id else "",
        "project": asset.project.name if asset.project else "",
        "board_id": str(asset.board_id) if asset.board_id else "",
        "board": str(asset.board) if asset.board else "",
        "component_id": str(asset.component_id) if asset.component_id else "",
        "component": str(asset.component) if asset.component else "",
        "created_at": asset.created_at.isoformat(),
        "updated_at": asset.updated_at.isoformat(),
    }


def _serialise_repository_link(link):
    return {
        "id": link.pk,
        "provider": link.provider,
        "provider_label": link.get_provider_display(),
        "name": link.name,
        "url": link.url,
        "local_path": link.local_path,
        "default_branch": link.default_branch,
        "created_at": link.created_at.isoformat(),
        "updated_at": link.updated_at.isoformat(),
    }


def _sha256_upload(uploaded):
    digest = hashlib.sha256()
    for chunk in uploaded.chunks():
        digest.update(chunk)
    try:
        uploaded.seek(0)
    except (AttributeError, OSError):
        pass
    return digest.hexdigest()


def _project_cost(project):
    total = Decimal("0")
    currency = settings.MAKERVAULT_CURRENCY
    for item in project.inventory_items.all():
        if item.purchase_price is not None:
            total += item.purchase_price * item.quantity
            currency = item.currency or currency
    return float(total), currency


def _serialise_project(project, detailed=False):
    gallery_qs = project.files.filter(category="image").order_by("-created_at")
    asset_qs = project.files.exclude(category="image").order_by("category", "-created_at")
    repository_qs = project.repositories.all().order_by("provider", "name")
    bom_count = getattr(project, "bom_count_value", None)
    if bom_count is None:
        bom_count = project.bom_items.count()
    cost, currency = _project_cost(project)
    data = {
        "id": str(project.id),
        "name": project.name,
        "slug": project.slug,
        "status": project.status,
        "status_label": project.get_status_display(),
        "summary": project.summary,
        "cover_image": _file_url(project.cover_image),
        "started_on": project.started_on.isoformat() if project.started_on else "",
        "completed_on": project.completed_on.isoformat() if project.completed_on else "",
        "created_by": project.created_by.get_username() if project.created_by else "",
        "inventory_count": project.inventory_items.count(),
        "gallery_count": gallery_qs.count(),
        "file_count": asset_qs.count(),
        "repository_count": repository_qs.count(),
        "bom_count": bom_count,
        "inventory_cost": cost,
        "currency": currency,
        "updated_at": project.updated_at.isoformat(),
        "created_at": project.created_at.isoformat(),
    }
    if detailed:
        bom_rows, bom_summary = _project_bom(project)
        data.update({
            "description": project.description,
            "notes": project.notes,
            "tags": project.tags or [],
            "reference_url": project.reference_url,
            "inventory": [_serialise_inventory(item) for item in project.inventory_items.select_related(
                "board__manufacturer", "component__manufacturer", "project"
            ).order_by("inventory_id")],
            "gallery": [
                {
                    "id": str(asset.id),
                    "name": asset.name,
                    "url": _file_url(asset.file),
                    "description": asset.description,
                    "created_at": asset.created_at.isoformat(),
                }
                for asset in gallery_qs
            ],
            "files": [_serialise_file_asset(asset) for asset in asset_qs],
            "repositories": [_serialise_repository_link(link) for link in repository_qs],
            "bom": bom_rows,
            "bom_summary": bom_summary,
            "file_categories": [
                {"value": value, "label": label}
                for value, label in FileAsset.CATEGORIES
                if value != "image"
            ],
        })
    return data

def _parse_date(value, field_name):
    raw = str(value or "").strip()
    if not raw:
        return None
    from datetime import date
    try:
        return date.fromisoformat(raw)
    except ValueError as exc:
        raise ValidationError({field_name: "Enter a valid date."}) from exc


def _normalise_tags(value):
    if value in (None, ""):
        return []
    values = value if isinstance(value, list) else str(value).split(",")
    output = []
    for tag in values:
        cleaned = str(tag).strip()
        if cleaned and cleaned not in output:
            output.append(cleaned[:60])
    return output[:30]


def _parse_decimal(value, field_name, allow_none=True):
    if value in (None, "") and allow_none:
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise ValidationError({field_name: "Enter a valid number."}) from exc


def _catalogue_decimal(value, field_name, decimal_places):
    parsed = _parse_decimal(value, field_name)
    if parsed is None:
        return None
    quantum = Decimal("1").scaleb(-decimal_places)
    return parsed.quantize(quantum)


def _resolve_filament_manufacturer(payload):
    dedicated_id = payload.get("filament_manufacturer_id")
    if dedicated_id:
        maker = FilamentManufacturer.objects.filter(pk=dedicated_id).first()
        if not maker:
            raise ValidationError({"filament_manufacturer_id": "Selected filament manufacturer was not found."})
        return maker

    name = str(payload.get("manufacturer_name") or "").strip()
    if name:
        maker, _ = FilamentManufacturer.objects.get_or_create(name=name)
        return maker

    legacy_id = payload.get("manufacturer_id")
    if legacy_id:
        legacy = Manufacturer.objects.filter(pk=legacy_id).first()
        if legacy:
            maker, _ = FilamentManufacturer.objects.get_or_create(name=legacy.name)
            return maker
        maker = FilamentManufacturer.objects.filter(pk=legacy_id).first()
        if maker:
            return maker
        raise ValidationError({"manufacturer_id": "Selected filament manufacturer was not found."})
    return None


def _resolve_printing_location(location_id, field_name="location_id"):
    if not location_id:
        return None
    location = PrintingLocation.objects.filter(pk=location_id).first()
    if not location:
        raise ValidationError({field_name: "Selected location was not found."})
    return location


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
        ).annotate(allocated_quantity=Sum("bom_allocations__quantity")).all()[:5000]
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
    base_qs = InventoryItem.objects.select_related(
        "board__manufacturer", "board__source", "component__manufacturer",
        "component__category", "component__source", "project"
    )
    if request.method == "GET":
        item = base_qs.filter(pk=item_id).first()
        if not item:
            return _error("Inventory item not found.", status=404)
        history = item.history.select_related("project", "changed_by").all()[:250]
        payload = _serialise_inventory(item)
        payload["board"] = _serialise_board(item.board, detailed=True) if item.board else None
        payload["component"] = _serialise_component(item.component) if item.component else None
        payload["history"] = [_serialise_inventory_history(entry) for entry in history]
        payload["bom_allocations"] = [
            {
                "id": allocation.id,
                "project_id": str(allocation.bom_item.project_id),
                "project_name": allocation.bom_item.project.name,
                "bom_item_id": allocation.bom_item_id,
                "bom_item_name": allocation.bom_item.display_name,
                "quantity": _float(allocation.quantity),
                "unit": allocation.bom_item.unit,
                "notes": allocation.notes,
            }
            for allocation in item.bom_allocations.select_related(
                "bom_item__project",
                "bom_item__board__manufacturer",
                "bom_item__component__manufacturer",
            ).order_by("bom_item__project__name", "bom_item__created_at")
        ]
        return JsonResponse({"item": payload})

    if request.method == "DELETE":
        denied = _require_permission(request, "core.delete_inventoryitem")
        if denied:
            return denied
        with transaction.atomic():
            item = InventoryItem.objects.select_for_update().filter(pk=item_id).first()
            if not item:
                return _error("Inventory item not found.", status=404)
            try:
                item.delete()
            except ProtectedError:
                return _error(
                    "This inventory item is allocated to a project BOM. Release its BOM allocations before deleting it.",
                    status=409,
                )
        return JsonResponse({"deleted": True})

    denied = _require_permission(request, "core.change_inventoryitem")
    if denied:
        return denied
    try:
        payload = _read_json(request)
        with transaction.atomic():
            item = InventoryItem.objects.select_for_update().filter(pk=item_id).first()
            if not item:
                return _error("Inventory item not found.", status=404)
            before = _inventory_snapshot(item)
            simple_fields = {
                "location", "serial_number", "supplier", "purchase_url", "notes", "custom_name"
            }
            for field in simple_fields:
                if field in payload:
                    setattr(item, field, str(payload[field] or "").strip())
    
            if "quantity" in payload:
                item.quantity = _parse_decimal(payload["quantity"], "quantity", allow_none=False)
                allocated = item.bom_allocations.aggregate(total=Sum("quantity"))["total"] or Decimal("0")
                if item.quantity < allocated:
                    raise ValidationError({
                        "quantity": f"Quantity cannot be lower than the {allocated} already allocated to BOMs."
                    })
            if "purchase_price" in payload:
                item.purchase_price = _parse_decimal(payload["purchase_price"], "purchase_price")
            if "currency" in payload:
                item.currency = str(payload["currency"] or settings.MAKERVAULT_CURRENCY).upper()[:3]
            if "status" in payload:
                item.status = str(payload["status"])
                if item.status in {"repair", "retired"} and item.bom_allocations.exists():
                    raise ValidationError({
                        "status": "Release BOM allocations before marking this inventory item as repair or retired."
                    })
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
                    allocation_projects = set(
                        item.bom_allocations.values_list("bom_item__project_id", flat=True).distinct()
                    )
                    if allocation_projects and allocation_projects != {project.id}:
                        raise ValidationError({
                            "project_id": "This inventory item has BOM allocations for another project. Release them before changing its project assignment."
                        })
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
        changed = enrich_board(board, online=True)
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
            if not request.user.is_staff:
                return _error(
                    "Remote catalogue image fetching is restricted to administrators; "
                    "editors can upload an image file instead.",
                    status=403,
                )
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
@require_http_methods(["GET", "POST"])
def files_lookup(request):
    if request.method == "GET":
        qs = FileAsset.objects.exclude(category="image").select_related(
            "project", "board__manufacturer", "component__manufacturer"
        )
        query = request.GET.get("q", "").strip()
        category = request.GET.get("category", "").strip()
        project_id = request.GET.get("project", "").strip()
        if query:
            qs = qs.filter(
                Q(name__icontains=query)
                | Q(description__icontains=query)
                | Q(version__icontains=query)
                | Q(project__name__icontains=query)
            )
        if category:
            if category not in dict(FileAsset.CATEGORIES) or category == "image":
                return _error("Unknown file category.")
            qs = qs.filter(category=category)
        if project_id == "__standalone__":
            qs = qs.filter(project__isnull=True)
        elif project_id:
            qs = qs.filter(project_id=project_id)
        return JsonResponse({
            "rows": [_serialise_file_asset(asset) for asset in qs.order_by("category", "-updated_at")[:5000]],
            "categories": [
                {"value": value, "label": label}
                for value, label in FileAsset.CATEGORIES
                if value != "image"
            ],
        })

    denied = _require_permission(request, "core.add_fileasset")
    if denied:
        return denied
    uploaded = request.FILES.get("file")
    if not uploaded:
        return _error("Choose a file to upload.")

    category = str(request.POST.get("category") or "other").strip()
    if category == "image" or category not in dict(FileAsset.CATEGORIES):
        return _error("Unknown file category.")

    project = None
    project_id = str(request.POST.get("project_id") or "").strip()
    if project_id:
        project = Project.objects.filter(pk=project_id).first()
        if not project:
            return _error("Selected project was not found.")
        project_denied = _require_permission(request, "core.change_project")
        if project_denied:
            return project_denied

    original_name = Path(uploaded.name or "file").name
    try:
        checksum = _sha256_upload(uploaded)
        asset = FileAsset(
            project=project,
            category=category,
            name=str(request.POST.get("name") or original_name).strip()[:255],
            version=str(request.POST.get("version") or "").strip()[:80],
            description=str(request.POST.get("description") or "").strip(),
            sha256=checksum,
            metadata={
                "original_name": original_name,
                "size_bytes": getattr(uploaded, "size", 0) or 0,
                "extension": Path(original_name).suffix.lower(),
                "uploaded_from": "files",
            },
        )
        asset.file = uploaded
        asset.full_clean()
        asset.save()
        if project:
            project.save(update_fields=["updated_at"])
        return JsonResponse({"file": _serialise_file_asset(asset)}, status=201)
    except ValidationError as exc:
        return _validation_response(exc)


@login_required
@require_http_methods(["PATCH", "DELETE"])
def file_detail(request, asset_id):
    asset = FileAsset.objects.select_related("project").filter(pk=asset_id).exclude(category="image").first()
    if not asset:
        return _error("File not found.", status=404)
    denied = _require_permission(request, "core.change_fileasset")
    if denied:
        return denied
    if asset.project:
        project_denied = _require_permission(request, "core.change_project")
        if project_denied:
            return project_denied

    previous_project = asset.project
    if request.method == "DELETE":
        stored_file = asset.file
        try:
            asset.delete()
        except ProtectedError:
            return _error(
                "This file is attached to a 3D model revision. Detach it from the model before deleting it.",
                status=409,
            )
        if stored_file:
            try:
                stored_file.delete(save=False)
            except OSError:
                pass
        if previous_project:
            previous_project.save(update_fields=["updated_at"])
        return JsonResponse({"deleted": True})

    try:
        payload = _read_json(request)
        if "name" in payload:
            asset.name = str(payload.get("name") or "").strip()[:255]
        if "version" in payload:
            asset.version = str(payload.get("version") or "").strip()[:80]
        if "description" in payload:
            asset.description = str(payload.get("description") or "").strip()
        if "category" in payload:
            category = str(payload.get("category") or "other").strip()
            if category == "image" or category not in dict(FileAsset.CATEGORIES):
                return _error("Unknown file category.")
            asset.category = category
        if "project_id" in payload:
            project_id = str(payload.get("project_id") or "").strip()
            if project_id:
                new_project = Project.objects.filter(pk=project_id).first()
                if not new_project:
                    return _error("Selected project was not found.")
                project_denied = _require_permission(request, "core.change_project")
                if project_denied:
                    return project_denied
                asset.project = new_project
            else:
                asset.project = None
        asset.full_clean()
        asset.save()
        if previous_project:
            previous_project.save(update_fields=["updated_at"])
        if asset.project and asset.project_id != getattr(previous_project, "id", None):
            asset.project.save(update_fields=["updated_at"])
        return JsonResponse({"file": _serialise_file_asset(asset)})
    except ValidationError as exc:
        return _validation_response(exc)


@login_required
@require_http_methods(["GET", "POST"])
def projects_lookup(request):
    if request.method == "GET":
        qs = Project.objects.select_related("created_by").prefetch_related(
            "inventory_items", "files", "repositories"
        ).annotate(bom_count_value=Count("bom_items", distinct=True)).all()
        return JsonResponse({"rows": [_serialise_project(project) for project in qs[:2000]]})

    denied = _require_permission(request, "core.add_project")
    if denied:
        return denied
    try:
        payload = _read_json(request)
        name = str(payload.get("name") or "").strip()
        if not name:
            return _error("Project name is required.")
        status = str(payload.get("status") or "idea")
        if status not in dict(Project.STATUS):
            return _error("Unknown project status.")
        project = Project(
            name=name,
            status=status,
            summary=str(payload.get("summary") or "").strip(),
            description=str(payload.get("description") or "").strip(),
            notes=str(payload.get("notes") or "").strip(),
            tags=_normalise_tags(payload.get("tags")),
            reference_url=str(payload.get("reference_url") or "").strip(),
            started_on=_parse_date(payload.get("started_on"), "started_on"),
            completed_on=_parse_date(payload.get("completed_on"), "completed_on"),
            created_by=request.user,
        )
        project.full_clean()
        project.save()
        project = Project.objects.select_related("created_by").prefetch_related("inventory_items", "files", "repositories").get(pk=project.pk)
        return JsonResponse({"project": _serialise_project(project, detailed=True)}, status=201)
    except ValidationError as exc:
        return _validation_response(exc)


@login_required
@require_http_methods(["GET", "PATCH", "DELETE"])
def project_detail(request, project_id):
    project = Project.objects.select_related("created_by").prefetch_related(
        "inventory_items__board__manufacturer",
        "inventory_items__component__manufacturer",
        "files",
        "repositories",
    ).filter(pk=project_id).first()
    if not project:
        return _error("Project not found.", status=404)

    if request.method == "GET":
        return JsonResponse({"project": _serialise_project(project, detailed=True)})

    if request.method == "DELETE":
        denied = _require_permission(request, "core.delete_project")
        if denied:
            return denied
        project.delete()
        return JsonResponse({"deleted": True})

    denied = _require_permission(request, "core.change_project")
    if denied:
        return denied
    try:
        payload = _read_json(request)
        for field in ("name", "summary", "description", "notes", "reference_url"):
            if field in payload:
                setattr(project, field, str(payload.get(field) or "").strip())
        if "status" in payload:
            status = str(payload.get("status") or "idea")
            if status not in dict(Project.STATUS):
                return _error("Unknown project status.")
            project.status = status
        if "tags" in payload:
            project.tags = _normalise_tags(payload.get("tags"))
        if "started_on" in payload:
            project.started_on = _parse_date(payload.get("started_on"), "started_on")
        if "completed_on" in payload:
            project.completed_on = _parse_date(payload.get("completed_on"), "completed_on")
        project.full_clean()
        project.save()
        project = Project.objects.select_related("created_by").prefetch_related(
            "inventory_items__board__manufacturer",
            "inventory_items__component__manufacturer",
            "files",
            "repositories",
        ).get(pk=project.pk)
        return JsonResponse({"project": _serialise_project(project, detailed=True)})
    except ValidationError as exc:
        return _validation_response(exc)


def _bom_catalogue_refs(payload):
    board_id = str(payload.get("board_id") or "").strip()
    component_id = str(payload.get("component_id") or "").strip()
    if board_id and component_id:
        raise ValidationError("Choose a board or component, not both.")

    board = None
    component = None
    if board_id:
        board = BoardModel.objects.filter(pk=board_id).first()
        if not board:
            raise ValidationError({"board_id": "Selected board was not found."})
    if component_id:
        component = ComponentModel.objects.filter(pk=component_id).first()
        if not component:
            raise ValidationError({"component_id": "Selected component was not found."})
    return board, component


def _validate_allocation_capacity(bom_item, inventory, quantity, *, excluding_id=None):
    quantity = Decimal(quantity)
    if quantity <= 0:
        raise ValidationError({"quantity": "Allocation quantity must be greater than zero."})

    bom_allocations = bom_item.allocations.all()
    inventory_allocations = inventory.bom_allocations.all()
    if excluding_id:
        bom_allocations = bom_allocations.exclude(pk=excluding_id)
        inventory_allocations = inventory_allocations.exclude(pk=excluding_id)

    bom_allocated = bom_allocations.aggregate(total=Sum("quantity"))["total"] or Decimal("0")
    inventory_allocated = inventory_allocations.aggregate(total=Sum("quantity"))["total"] or Decimal("0")
    bom_remaining = (bom_item.quantity or Decimal("0")) - bom_allocated
    inventory_remaining = (inventory.quantity or Decimal("0")) - inventory_allocated

    if quantity > bom_remaining:
        raise ValidationError({
            "quantity": f"Only {bom_remaining} {bom_item.unit} remain unallocated on this BOM line."
        })
    if quantity > inventory_remaining:
        raise ValidationError({
            "quantity": f"Only {inventory_remaining} remain available in inventory item {inventory.inventory_id}."
        })


@login_required
@require_http_methods(["POST"])
def project_bom_items(request, project_id):
    project = Project.objects.filter(pk=project_id).first()
    if not project:
        return _error("Project not found.", status=404)
    denied = _require_permission(request, "core.change_project")
    if denied:
        return denied

    try:
        payload = _read_json(request)
        board, component = _bom_catalogue_refs(payload)
        item = BOMItem(
            project=project,
            board=board,
            component=component,
            custom_name=str(payload.get("custom_name") or "").strip()[:255],
            quantity=_parse_decimal(payload.get("quantity", 1), "quantity", allow_none=False),
            unit=str(payload.get("unit") or "item").strip()[:40],
            unit_cost=_parse_decimal(payload.get("unit_cost"), "unit_cost"),
            currency=str(payload.get("currency") or settings.MAKERVAULT_CURRENCY).upper()[:3],
            notes=str(payload.get("notes") or "").strip(),
        )
        item.full_clean()
        item.save()
        project.save(update_fields=["updated_at"])
        item = BOMItem.objects.select_related("board__manufacturer", "component__manufacturer").get(pk=item.pk)
        return JsonResponse({"bom_item": _serialise_bom_item(item)}, status=201)
    except ValidationError as exc:
        return _validation_response(exc)
    except ValueError as exc:
        return _error(str(exc))


@login_required
@require_http_methods(["PATCH", "DELETE"])
def project_bom_item_detail(request, project_id, bom_id):
    project = Project.objects.filter(pk=project_id).first()
    if not project:
        return _error("Project not found.", status=404)
    denied = _require_permission(request, "core.change_project")
    if denied:
        return denied

    with transaction.atomic():
        item = BOMItem.objects.select_for_update().select_related(
            "project"
        ).filter(pk=bom_id, project=project).first()
        if not item:
            return _error("BOM item not found.", status=404)

        if request.method == "DELETE":
            allocations = list(item.allocations.select_related("inventory_item").all())
            for allocation in allocations:
                _record_bom_allocation_history(allocation, request.user, "bom_released")
            item.delete()
            project.save(update_fields=["updated_at"])
            return JsonResponse({"deleted": True})

        try:
            payload = _read_json(request)
            new_board, new_component = _bom_catalogue_refs({
                "board_id": payload.get("board_id", item.board_id or ""),
                "component_id": payload.get("component_id", item.component_id or ""),
            })
            if "board_id" in payload or "component_id" in payload:
                item.board = new_board
                item.component = new_component
            if "custom_name" in payload:
                item.custom_name = str(payload.get("custom_name") or "").strip()[:255]
            if "quantity" in payload:
                item.quantity = _parse_decimal(payload.get("quantity"), "quantity", allow_none=False)
            if "unit" in payload:
                item.unit = str(payload.get("unit") or "").strip()[:40]
            if "unit_cost" in payload:
                item.unit_cost = _parse_decimal(payload.get("unit_cost"), "unit_cost")
            if "currency" in payload:
                item.currency = str(payload.get("currency") or settings.MAKERVAULT_CURRENCY).upper()[:3]
            if "notes" in payload:
                item.notes = str(payload.get("notes") or "").strip()

            allocated = item.allocations.aggregate(total=Sum("quantity"))["total"] or Decimal("0")
            if item.quantity < allocated:
                raise ValidationError({
                    "quantity": f"Quantity cannot be lower than the {allocated} already allocated."
                })

            for allocation in item.allocations.select_related("inventory_item").all():
                inventory = allocation.inventory_item
                if item.board_id and inventory.board_id != item.board_id:
                    raise ValidationError({"board_id": "Release incompatible allocations before changing the BOM board."})
                if item.component_id and inventory.component_id != item.component_id:
                    raise ValidationError({"component_id": "Release incompatible allocations before changing the BOM component."})

            item.full_clean()
            item.save()
            project.save(update_fields=["updated_at"])
            return JsonResponse({"bom_item": _serialise_bom_item(item)})
        except ValidationError as exc:
            return _validation_response(exc)
        except ValueError as exc:
            return _error(str(exc))


@login_required
@require_http_methods(["POST"])
def project_bom_allocations(request, project_id, bom_id):
    project = Project.objects.filter(pk=project_id).first()
    if not project:
        return _error("Project not found.", status=404)
    denied = _require_permission(request, "core.change_project")
    if denied:
        return denied

    try:
        payload = _read_json(request)
        create_payload = payload.get("create_inventory")
        inventory_id = str(payload.get("inventory_item_id") or "").strip()
        if not inventory_id and not isinstance(create_payload, dict):
            return _error("Choose an inventory item or create a new one from this BOM line.")
        if inventory_id and isinstance(create_payload, dict):
            return _error("Choose existing inventory or create new inventory, not both.")

        with transaction.atomic():
            bom_item = BOMItem.objects.select_for_update().select_related(
                "project"
            ).filter(pk=bom_id, project=project).first()
            if not bom_item:
                return _error("BOM item not found.", status=404)

            quantity = _parse_decimal(payload.get("quantity", 1), "quantity", allow_none=False)

            if isinstance(create_payload, dict):
                permission_denied = _require_permission(request, "core.add_inventoryitem")
                if permission_denied:
                    return permission_denied

                if bom_item.board_id:
                    item_type = "board"
                    board = BoardModel.objects.filter(pk=bom_item.board_id).first()
                    component = None
                    custom_name = ""
                elif bom_item.component_id:
                    item_type = "component"
                    board = None
                    component = ComponentModel.objects.filter(pk=bom_item.component_id).first()
                    custom_name = ""
                else:
                    item_type = "other"
                    board = None
                    component = None
                    custom_name = bom_item.display_name[:255]

                stock_quantity = _parse_decimal(
                    create_payload.get("quantity", quantity),
                    "inventory_quantity",
                    allow_none=False,
                )
                assigned_project = None
                if bool(create_payload.get("assign_to_project")):
                    assigned_project = project

                inventory = InventoryItem(
                    inventory_id=(
                        str(create_payload.get("inventory_id") or "").strip()
                        or _next_inventory_id(item_type)
                    ),
                    item_type=item_type,
                    board=board,
                    component=component,
                    custom_name=custom_name,
                    quantity=stock_quantity,
                    status=str(create_payload.get("status") or "available"),
                    project=assigned_project,
                    location=str(create_payload.get("location") or "").strip(),
                    serial_number=str(create_payload.get("serial_number") or "").strip(),
                    purchase_price=_parse_decimal(
                        create_payload.get("purchase_price"),
                        "purchase_price",
                    ),
                    currency=str(
                        create_payload.get("currency") or settings.MAKERVAULT_CURRENCY
                    ).upper()[:3],
                    supplier=str(create_payload.get("supplier") or "").strip(),
                    purchase_url=str(create_payload.get("purchase_url") or "").strip(),
                    notes=str(create_payload.get("notes") or "").strip(),
                )
                inventory.full_clean()
                inventory.save()
                _record_inventory_history(inventory, request.user, created=True)
            else:
                inventory = InventoryItem.objects.select_for_update().filter(pk=inventory_id).first()
                if not inventory:
                    return _error("Inventory item not found.", status=404)
                if BOMAllocation.objects.filter(
                    bom_item=bom_item, inventory_item=inventory
                ).exists():
                    return _error("This inventory item is already allocated to this BOM line.")

            allocation = BOMAllocation(
                bom_item=bom_item,
                inventory_item=inventory,
                quantity=quantity,
                notes=str(payload.get("notes") or "").strip(),
                allocated_by=request.user,
            )
            allocation.full_clean()
            _validate_allocation_capacity(bom_item, inventory, quantity)
            allocation.save()
            _record_bom_allocation_history(allocation, request.user, "bom_allocated")
            project.save(update_fields=["updated_at"])

            inventory = InventoryItem.objects.select_related(
                "board__manufacturer", "component__manufacturer", "project"
            ).get(pk=inventory.pk)
            allocation.inventory_item = inventory
            return JsonResponse({
                "allocation": _serialise_bom_allocation(allocation),
                "inventory_item": _serialise_inventory(inventory),
                "created_inventory": isinstance(create_payload, dict),
            }, status=201)
    except ValidationError as exc:
        return _validation_response(exc)
    except (ValueError, IntegrityError) as exc:
        return _error(str(exc))


@login_required
@require_http_methods(["PATCH", "DELETE"])
def project_bom_allocation_detail(request, project_id, bom_id, allocation_id):
    project = Project.objects.filter(pk=project_id).first()
    if not project:
        return _error("Project not found.", status=404)
    denied = _require_permission(request, "core.change_project")
    if denied:
        return denied

    try:
        with transaction.atomic():
            allocation = BOMAllocation.objects.select_for_update().select_related(
                "bom_item", "bom_item__project", "inventory_item",
            ).filter(
                pk=allocation_id,
                bom_item_id=bom_id,
                bom_item__project=project,
            ).first()
            if not allocation:
                return _error("BOM allocation not found.", status=404)

            inventory = InventoryItem.objects.select_for_update().get(pk=allocation.inventory_item_id)
            bom_item = BOMItem.objects.select_for_update().get(pk=allocation.bom_item_id)

            if request.method == "DELETE":
                _record_bom_allocation_history(allocation, request.user, "bom_released")
                allocation.delete()
                project.save(update_fields=["updated_at"])
                return JsonResponse({"deleted": True})

            payload = _read_json(request)
            previous_quantity = allocation.quantity
            if "quantity" in payload:
                allocation.quantity = _parse_decimal(payload.get("quantity"), "quantity", allow_none=False)
            if "notes" in payload:
                allocation.notes = str(payload.get("notes") or "").strip()
            allocation.bom_item = bom_item
            allocation.inventory_item = inventory
            allocation.full_clean()
            _validate_allocation_capacity(
                bom_item, inventory, allocation.quantity, excluding_id=allocation.pk
            )
            allocation.save()
            if allocation.quantity != previous_quantity:
                _record_bom_allocation_history(
                    allocation, request.user, "bom_allocated", previous_quantity=previous_quantity
                )
            project.save(update_fields=["updated_at"])
            return JsonResponse({"allocation": _serialise_bom_allocation(allocation)})
    except ValidationError as exc:
        return _validation_response(exc)
    except ValueError as exc:
        return _error(str(exc))


@login_required
@require_http_methods(["POST", "DELETE"])
def project_cover(request, project_id):
    project = Project.objects.select_related("created_by").prefetch_related("inventory_items", "files", "repositories").filter(pk=project_id).first()
    if not project:
        return _error("Project not found.", status=404)
    denied = _require_permission(request, "core.change_project")
    if denied:
        return denied

    if request.method == "DELETE":
        if project.cover_image:
            project.cover_image.delete(save=False)
        project.cover_image = None
        project.save(update_fields=["cover_image", "updated_at"])
        return JsonResponse({"project": _serialise_project(project, detailed=True)})

    uploaded = request.FILES.get("image")
    if not uploaded:
        return _error("Choose an image file.")
    try:
        content, filename = sanitise_uploaded_image(uploaded, project.slug or project.name)
        if project.cover_image:
            project.cover_image.delete(save=False)
        project.cover_image.save(filename, content, save=False)
        project.save(update_fields=["cover_image", "updated_at"])
        return JsonResponse({"project": _serialise_project(project, detailed=True)})
    except CatalogueImageError as exc:
        return _error(str(exc))


@login_required
@require_http_methods(["POST"])
def project_gallery(request, project_id):
    project = Project.objects.filter(pk=project_id).first()
    if not project:
        return _error("Project not found.", status=404)
    denied = _require_permission(request, "core.change_project")
    if denied:
        return denied
    uploaded = request.FILES.get("image")
    if not uploaded:
        return _error("Choose an image file.")
    try:
        content, filename = sanitise_uploaded_image(uploaded, f"{project.slug}-gallery")
        asset = FileAsset(
            project=project,
            category="image",
            name=str(request.POST.get("name") or uploaded.name or "Project image")[:255],
            description=str(request.POST.get("description") or "").strip(),
        )
        asset.file.save(filename, content, save=False)
        asset.full_clean()
        asset.save()
        return JsonResponse({
            "image": {
                "id": str(asset.id),
                "name": asset.name,
                "url": _file_url(asset.file),
                "description": asset.description,
                "created_at": asset.created_at.isoformat(),
            }
        }, status=201)
    except CatalogueImageError as exc:
        return _error(str(exc))


@login_required
@require_http_methods(["DELETE"])
def project_gallery_delete(request, project_id, asset_id):
    project = Project.objects.filter(pk=project_id).first()
    if not project:
        return _error("Project not found.", status=404)
    denied = _require_permission(request, "core.change_project")
    if denied:
        return denied
    asset = FileAsset.objects.filter(pk=asset_id, project=project, category="image").first()
    if not asset:
        return _error("Project image not found.", status=404)
    if asset.file:
        try:
            asset.file.delete(save=False)
        except OSError:
            pass
    asset.delete()
    return JsonResponse({"deleted": True})


@login_required
@require_http_methods(["POST"])
def project_files(request, project_id):
    project = Project.objects.filter(pk=project_id).first()
    if not project:
        return _error("Project not found.", status=404)
    denied = _require_permission(request, "core.change_project")
    if denied:
        return denied

    uploaded = request.FILES.get("file")
    if not uploaded:
        return _error("Choose a file to upload.")

    category = str(request.POST.get("category") or "other").strip()
    allowed_categories = dict(FileAsset.CATEGORIES)
    if category == "image":
        return _error("Use the project gallery for project photos.")
    if category not in allowed_categories:
        return _error("Unknown file category.")

    original_name = Path(uploaded.name or "project-file").name
    try:
        checksum = _sha256_upload(uploaded)
        asset = FileAsset(
            project=project,
            category=category,
            name=str(request.POST.get("name") or original_name)[:255],
            version=str(request.POST.get("version") or "").strip()[:80],
            description=str(request.POST.get("description") or "").strip(),
            sha256=checksum,
            metadata={
                "original_name": original_name,
                "size_bytes": getattr(uploaded, "size", 0) or 0,
                "extension": Path(original_name).suffix.lower(),
            },
        )
        asset.file = uploaded
        asset.full_clean()
        asset.save()
        project.save(update_fields=["updated_at"])
        return JsonResponse({"file": _serialise_file_asset(asset)}, status=201)
    except ValidationError as exc:
        return _validation_response(exc)


@login_required
@require_http_methods(["PATCH", "DELETE"])
def project_file_detail(request, project_id, asset_id):
    project = Project.objects.filter(pk=project_id).first()
    if not project:
        return _error("Project not found.", status=404)
    denied = _require_permission(request, "core.change_project")
    if denied:
        return denied
    asset = FileAsset.objects.filter(pk=asset_id, project=project).exclude(category="image").first()
    if not asset:
        return _error("Project file not found.", status=404)

    if request.method == "DELETE":
        if asset.file:
            try:
                asset.file.delete(save=False)
            except OSError:
                pass
        asset.delete()
        project.save(update_fields=["updated_at"])
        return JsonResponse({"deleted": True})

    try:
        payload = _read_json(request)
        if "name" in payload:
            asset.name = str(payload.get("name") or "").strip()[:255]
        if "version" in payload:
            asset.version = str(payload.get("version") or "").strip()[:80]
        if "description" in payload:
            asset.description = str(payload.get("description") or "").strip()
        if "category" in payload:
            category = str(payload.get("category") or "other").strip()
            if category == "image" or category not in dict(FileAsset.CATEGORIES):
                return _error("Unknown file category.")
            asset.category = category
        asset.full_clean()
        asset.save()
        project.save(update_fields=["updated_at"])
        return JsonResponse({"file": _serialise_file_asset(asset)})
    except ValidationError as exc:
        return _validation_response(exc)


@login_required
@require_http_methods(["POST"])
def project_repositories(request, project_id):
    project = Project.objects.filter(pk=project_id).first()
    if not project:
        return _error("Project not found.", status=404)
    denied = _require_permission(request, "core.change_project")
    if denied:
        return denied
    try:
        payload = _read_json(request)
        provider = str(payload.get("provider") or "other").strip()
        if provider not in dict(RepositoryLink.PROVIDERS):
            return _error("Unknown repository provider.")
        name = str(payload.get("name") or "").strip()
        url = str(payload.get("url") or "").strip()
        local_path = str(payload.get("local_path") or "").strip()
        if not name:
            return _error("Repository name is required.")
        if not url and not local_path:
            return _error("Enter a repository URL or local path.")
        link = RepositoryLink(
            project=project,
            provider=provider,
            name=name[:255],
            url=url,
            local_path=local_path[:500],
            default_branch=str(payload.get("default_branch") or "").strip()[:120],
        )
        link.full_clean()
        link.save()
        project.save(update_fields=["updated_at"])
        return JsonResponse({"repository": _serialise_repository_link(link)}, status=201)
    except ValidationError as exc:
        return _validation_response(exc)


@login_required
@require_http_methods(["PATCH", "DELETE"])
def project_repository_detail(request, project_id, repository_id):
    project = Project.objects.filter(pk=project_id).first()
    if not project:
        return _error("Project not found.", status=404)
    denied = _require_permission(request, "core.change_project")
    if denied:
        return denied
    link = RepositoryLink.objects.filter(pk=repository_id, project=project).first()
    if not link:
        return _error("Repository link not found.", status=404)

    if request.method == "DELETE":
        link.delete()
        project.save(update_fields=["updated_at"])
        return JsonResponse({"deleted": True})

    try:
        payload = _read_json(request)
        for field, limit in (("name", 255), ("local_path", 500), ("default_branch", 120)):
            if field in payload:
                setattr(link, field, str(payload.get(field) or "").strip()[:limit])
        if "url" in payload:
            link.url = str(payload.get("url") or "").strip()
        if "provider" in payload:
            provider = str(payload.get("provider") or "other").strip()
            if provider not in dict(RepositoryLink.PROVIDERS):
                return _error("Unknown repository provider.")
            link.provider = provider
        if not link.name:
            return _error("Repository name is required.")
        if not link.url and not link.local_path:
            return _error("Enter a repository URL or local path.")
        link.full_clean()
        link.save()
        project.save(update_fields=["updated_at"])
        return JsonResponse({"repository": _serialise_repository_link(link)})
    except ValidationError as exc:
        return _validation_response(exc)


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


def _serialise_catalogue_maintenance(config):
    return {
        "enabled": config.enabled,
        "interval_hours": config.interval_hours,
        "check_board_data": config.check_board_data,
        "check_images": config.check_images,
        "last_run_at": config.last_run_at.isoformat() if config.last_run_at else "",
        "next_run_at": config.next_run_at.isoformat() if config.next_run_at else "",
        "last_triggered_by": config.last_triggered_by,
        "server_board_enrichment_enabled": bool(settings.ENRICH_BOARD_CATALOGUE),
        "server_image_seeding_enabled": bool(settings.SEED_CATALOGUE_IMAGES),
    }


@login_required
@require_http_methods(["GET", "PATCH"])
def catalogue_maintenance_settings(request):
    if not request.user.is_staff:
        return _error("Administrator access is required.", status=403)

    config, _ = CatalogueMaintenanceSettings.objects.get_or_create(singleton_key=1)
    if request.method == "GET":
        return JsonResponse({"settings": _serialise_catalogue_maintenance(config)})

    try:
        payload = _read_json(request)
        if "enabled" in payload:
            config.enabled = bool(payload["enabled"])
        if "check_board_data" in payload:
            config.check_board_data = bool(payload["check_board_data"])
        if "check_images" in payload:
            config.check_images = bool(payload["check_images"])
        if "interval_hours" in payload:
            try:
                config.interval_hours = int(payload["interval_hours"])
            except (TypeError, ValueError) as exc:
                raise ValidationError({"interval_hours": "Enter a whole number of hours."}) from exc

        config.full_clean()
        config.next_run_at = (
            timezone.now() + timedelta(hours=config.interval_hours)
            if config.enabled else None
        )
        config.save()
        return JsonResponse({"settings": _serialise_catalogue_maintenance(config)})
    except ValidationError as exc:
        return _validation_response(exc)


@login_required
@require_http_methods(["POST"])
def catalogue_maintenance_run_now(request):
    if not request.user.is_staff:
        return _error("Administrator access is required.", status=403)
    config, queued = queue_catalogue_maintenance_now(
        triggered_by=f"user:{request.user.get_username()}"
    )
    return JsonResponse({
        "settings": _serialise_catalogue_maintenance(config),
        "queued": queued,
    })


def _serialise_printing_file_link(link):
    asset = link.file_asset
    return {
        "id": str(link.id),
        "role": link.role,
        "role_label": link.get_role_display(),
        "is_primary": link.is_primary,
        "notes": link.notes,
        "file": {
            "id": str(asset.id),
            "name": asset.name,
            "category": asset.category,
            "category_label": asset.get_category_display(),
            "filename": Path(asset.file.name).name if asset.file else "",
            "url": _file_url(asset.file),
            "project_id": str(asset.project_id) if asset.project_id else None,
            "project": asset.project.name if asset.project else "",
        },
    }


def _serialise_printing_model(model):
    revisions = []
    for revision in model.revisions.all():
        revisions.append({
            "id": str(revision.id),
            "version": revision.version,
            "notes": revision.notes,
            "source_url": revision.source_url,
            "assets": [_serialise_printing_file_link(link) for link in revision.assets.all()],
            "created_at": revision.created_at.isoformat(),
        })
    return {
        "id": str(model.id),
        "name": model.name,
        "description": model.description,
        "source_url": model.source_url,
        "license": model.license,
        "tags": model.tags,
        "project_id": str(model.project_id) if model.project_id else None,
        "project": model.project.name if model.project else "",
        "revision_count": len(revisions),
        "revisions": revisions,
        "updated_at": model.updated_at.isoformat(),
    }


def _serialise_printing_location(location):
    return {
        "id": str(location.id),
        "name": location.name,
        "kind": location.kind,
        "kind_label": location.get_kind_display(),
        "notes": location.notes,
    }


def _serialise_printer_catalog_model(item):
    return {
        "id": str(item.id),
        "manufacturer_id": str(item.manufacturer_id),
        "manufacturer": item.manufacturer.name,
        "name": item.name,
        "display_name": str(item),
        "build_volume": {
            "x": _float(item.build_volume_x_mm),
            "y": _float(item.build_volume_y_mm),
            "z": _float(item.build_volume_z_mm),
        },
        "nozzle_mm": _float(item.nozzle_mm),
        "filament_diameter_mm": _float(item.filament_diameter_mm),
        "max_nozzle_temp_c": item.max_nozzle_temp_c,
        "max_bed_temp_c": item.max_bed_temp_c,
        "enclosed": item.enclosed,
        "multi_material_system": item.multi_material_system,
        "multi_material_label": item.get_multi_material_system_display() if item.multi_material_system else "",
        "max_multi_material_units": item.max_multi_material_units,
        "features": item.features or {},
        "source_url": item.source_url,
    }


def _serialise_external_spool_link(link):
    return {
        "id": str(link.id),
        "provider": link.provider,
        "provider_label": link.get_provider_display(),
        "external_id": link.external_id,
        "external_url": link.external_url,
        "sync_direction": link.sync_direction,
        "sync_direction_label": link.get_sync_direction_display(),
        "last_synced_at": link.last_synced_at.isoformat() if link.last_synced_at else None,
    }


def _serialise_spool(spool):
    filament = spool.filament
    maker = filament.filament_manufacturer or filament.manufacturer
    placement = ""
    placement_type = ""
    if spool.assigned_printer_id:
        placement = spool.assigned_printer.name
        placement_type = "printer"
    elif spool.storage_location_id:
        placement = spool.storage_location.name
        placement_type = "location"
    elif spool.location:
        placement = spool.location
        placement_type = "legacy"
    return {
        "id": str(spool.id),
        "spool_id": spool.spool_id,
        "filament": str(filament),
        "filament_id": str(filament.id),
        "manufacturer": maker.name if maker else "",
        "material": filament.material,
        "color_name": filament.color_name,
        "color_hex": filament.color_hex,
        "color_hexes": filament.color_hexes or [],
        "transparency": filament.transparency,
        "transparency_label": filament.get_transparency_display(),
        "multi_color_direction": filament.multi_color_direction,
        "finish": filament.finish,
        "pattern": filament.pattern,
        "glow": filament.glow,
        "diameter_mm": _float(filament.diameter_mm),
        "initial_weight_g": _float(spool.initial_weight_g),
        "remaining_weight_g": _float(spool.remaining_weight_g),
        "status": spool.status,
        "status_label": spool.get_status_display(),
        "location": placement,
        "placement_type": placement_type,
        "storage_location_id": str(spool.storage_location_id) if spool.storage_location_id else None,
        "assigned_printer_id": str(spool.assigned_printer_id) if spool.assigned_printer_id else None,
        "external_links": [_serialise_external_spool_link(link) for link in spool.external_links.all()],
        "loaded_slots": [
            {
                "printer_id": str(slot.printer_id),
                "printer": slot.printer.name,
                "system": slot.system,
                "system_label": slot.get_system_display(),
                "unit_index": slot.unit_index,
                "slot_index": slot.slot_index,
            }
            for slot in spool.printer_slots.all()
            if slot.is_loaded
        ],
        "updated_at": spool.updated_at.isoformat(),
    }

def _serialise_printer_slot(slot):
    return {
        "id": str(slot.id),
        "system": slot.system,
        "system_label": slot.get_system_display(),
        "unit_index": slot.unit_index,
        "slot_index": slot.slot_index,
        "spool_id": str(slot.spool_id) if slot.spool_id else None,
        "spool_code": slot.spool.spool_id if slot.spool else "",
        "material": slot.material or (slot.spool.filament.material if slot.spool else ""),
        "color_name": slot.color_name or (slot.spool.filament.color_name if slot.spool else ""),
        "color_hex": slot.color_hex or (slot.spool.filament.color_hex if slot.spool else ""),
        "remaining_weight_g": _float(slot.remaining_weight_g),
        "rfid_uid": slot.rfid_uid,
        "external_ref": slot.external_ref,
        "is_loaded": slot.is_loaded,
        "last_seen_at": slot.last_seen_at.isoformat() if slot.last_seen_at else None,
    }


def _serialise_printer(printer):
    maker = printer.printer_manufacturer or printer.manufacturer
    catalogue = printer.catalog_model
    return {
        "id": str(printer.id),
        "name": printer.name,
        "manufacturer_id": str(printer.printer_manufacturer_id) if printer.printer_manufacturer_id else None,
        "manufacturer": maker.name if maker else "",
        "catalog_model_id": str(printer.catalog_model_id) if printer.catalog_model_id else None,
        "model": printer.model,
        "serial_number": printer.serial_number,
        "location_id": str(printer.printing_location_id) if printer.printing_location_id else None,
        "location": printer.printing_location.name if printer.printing_location else printer.location,
        "is_active": printer.is_active,
        "connection_host": printer.connection_host,
        "build_volume": {
            "x": _float(printer.build_volume_x_mm),
            "y": _float(printer.build_volume_y_mm),
            "z": _float(printer.build_volume_z_mm),
        },
        "nozzle_mm": _float(printer.nozzle_mm),
        "catalogue": _serialise_printer_catalog_model(catalogue) if catalogue else None,
        "slots": [_serialise_printer_slot(slot) for slot in printer.filament_slots.all()],
        "updated_at": printer.updated_at.isoformat(),
    }

def _serialise_print_material_usage(usage):
    return {
        "id": str(usage.id),
        "spool_id": str(usage.spool_id) if usage.spool_id else None,
        "spool": usage.spool.spool_id if usage.spool else "",
        "filament_id": str(usage.filament_id) if usage.filament_id else None,
        "filament": str(usage.filament) if usage.filament else "",
        "printer_slot_id": str(usage.printer_slot_id) if usage.printer_slot_id else None,
        "used_g": _float(usage.used_g),
        "waste_g": _float(usage.waste_g),
        "material_cost": _float(usage.material_cost),
        "currency": usage.currency,
        "notes": usage.notes,
    }


def _serialise_print_job(job):
    usages = list(job.material_usages.all())
    total_used = sum((usage.used_g or Decimal("0") for usage in usages), Decimal("0"))
    total_waste = sum((usage.waste_g or Decimal("0") for usage in usages), Decimal("0"))
    costs = [usage.material_cost for usage in usages if usage.material_cost is not None]
    total_cost = sum(costs, Decimal("0")) if costs else None
    return {
        "id": str(job.id),
        "status": job.status,
        "status_label": job.get_status_display(),
        "quantity": job.quantity,
        "printer_id": str(job.printer_id),
        "printer": job.printer.name,
        "project_id": str(job.project_id) if job.project_id else None,
        "project": job.project.name if job.project else "",
        "model_revision_id": str(job.model_revision_id) if job.model_revision_id else None,
        "model": job.model_revision.model.name if job.model_revision else "",
        "revision": job.model_revision.version if job.model_revision else "",
        "material_usages": [_serialise_print_material_usage(usage) for usage in usages],
        "filament_used_g": _float(total_used),
        "waste_g": _float(total_waste),
        "material_cost": _float(total_cost),
        "actual_minutes": job.actual_minutes,
        "created_at": job.created_at.isoformat(),
    }


@login_required
@require_http_methods(["GET"])
def printing_overview(request):
    printers = list(
        Printer.objects.select_related(
            "manufacturer",
            "printer_manufacturer",
            "catalog_model__manufacturer",
            "printing_location",
        ).prefetch_related(
            "filament_slots__spool__filament__manufacturer",
            "filament_slots__spool__filament__filament_manufacturer",
        )
    )
    spools = list(
        Spool.objects.select_related(
            "filament__manufacturer",
            "filament__filament_manufacturer",
            "storage_location",
            "assigned_printer",
        ).prefetch_related(
            "external_links",
            "printer_slots__printer",
        )
    )
    models_3d = list(
        Model3D.objects.select_related("project").prefetch_related(
            "revisions__assets__file_asset__project"
        )
    )
    recent_prints = list(
        PrintJob.objects.select_related(
            "printer",
            "project",
            "model_revision__model",
        ).prefetch_related(
            "material_usages__spool__filament__manufacturer",
            "material_usages__spool__filament__filament_manufacturer",
            "material_usages__filament__manufacturer",
            "material_usages__filament__filament_manufacturer",
            "material_usages__printer_slot",
        )[:12]
    )

    loaded_slots = sum(
        1
        for printer in printers
        for slot in printer.filament_slots.all()
        if slot.is_loaded
    )
    linked_spools = sum(1 for spool in spools if list(spool.external_links.all()))

    return JsonResponse({
        "summary": {
            "printers": len(printers),
            "active_printers": sum(1 for printer in printers if printer.is_active),
            "models": len(models_3d),
            "spools": len(spools),
            "filaments": FilamentProduct.objects.count(),
            "loaded_slots": loaded_slots,
            "externally_linked_spools": linked_spools,
            "print_jobs": PrintJob.objects.count(),
        },
        "printers": [_serialise_printer(printer) for printer in printers],
        "spools": [_serialise_spool(spool) for spool in spools],
        "filaments": [
            _serialise_filament_product(item)
            for item in FilamentProduct.objects.select_related(
                "manufacturer", "filament_manufacturer", "source"
            ).all()
        ],
        "printer_manufacturers": [
            {"id": str(item.id), "name": item.name, "website": item.website}
            for item in PrinterManufacturer.objects.order_by("name")
        ],
        "printer_catalogue_models": [
            _serialise_printer_catalog_model(item)
            for item in PrinterCatalogModel.objects.select_related("manufacturer").all()
        ],
        "filament_manufacturers": [
            {"id": str(item.id), "name": item.name, "website": item.website}
            for item in FilamentManufacturer.objects.order_by("name")
        ],
        "locations": [
            _serialise_printing_location(item)
            for item in PrintingLocation.objects.order_by("name")
        ],
        "common_filament_materials": COMMON_FILAMENT_MATERIALS,
        "model_files": [
            _serialise_file_asset(asset)
            for asset in FileAsset.objects.filter(category__in=["mesh", "slicer", "cad"])
                .select_related("project", "board__manufacturer", "component__manufacturer")
                .order_by("category", "name")[:5000]
        ],
        "models": [_serialise_printing_model(model) for model in models_3d],
        "recent_prints": [_serialise_print_job(job) for job in recent_prints],
    })


def _serialise_filament_product(filament):
    return {
        "id": str(filament.id),
        "name": filament.name,
        "display_name": str(filament),
        "manufacturer_id": str(filament.filament_manufacturer_id) if filament.filament_manufacturer_id else None,
        "manufacturer": (
            filament.filament_manufacturer.name
            if filament.filament_manufacturer
            else filament.manufacturer.name if filament.manufacturer else ""
        ),
        "material": filament.material,
        "color_name": filament.color_name,
        "color_hex": filament.color_hex,
        "color_hexes": filament.color_hexes or [],
        "transparency": filament.transparency,
        "transparency_label": filament.get_transparency_display(),
        "multi_color_direction": filament.multi_color_direction,
        "finish": filament.finish,
        "pattern": filament.pattern,
        "glow": filament.glow,
        "diameter_mm": _float(filament.diameter_mm),
        "density_g_cm3": _float(filament.density_g_cm3),
        "nominal_weight_g": _float(filament.nominal_weight_g),
        "empty_spool_weight_g": _float(filament.empty_spool_weight_g),
        "nozzle_temp_min_c": filament.nozzle_temp_min_c,
        "nozzle_temp_max_c": filament.nozzle_temp_max_c,
        "bed_temp_min_c": filament.bed_temp_min_c,
        "bed_temp_max_c": filament.bed_temp_max_c,
        "drying_temp_c": filament.drying_temp_c,
        "drying_time_hours": _float(filament.drying_time_hours),
        "source": filament.source.name if filament.source else "Manual",
        "source_type": filament.source.source_type if filament.source else "manual",
        "source_url": filament.source.url if filament.source else "",
        "source_license": (filament.source.raw_metadata or {}).get("license", "") if filament.source else "",
        "updated_at": filament.updated_at.isoformat(),
    }


@login_required
@require_http_methods(["GET", "POST"])
def printing_filaments(request):
    if request.method == "GET":
        qs = FilamentProduct.objects.select_related(
            "manufacturer", "filament_manufacturer", "source"
        ).all()
        return JsonResponse({"rows": [_serialise_filament_product(item) for item in qs]})

    denied = _require_permission(request, "core.add_filamentproduct")
    if denied:
        return denied
    try:
        payload = _read_json(request)
        filament_manufacturer = _resolve_filament_manufacturer(payload)
        item = FilamentProduct(
            filament_manufacturer=filament_manufacturer,
            name=str(payload.get("name") or "").strip(),
            material=str(payload.get("material") or "").strip(),
            color_name=str(payload.get("color_name") or "").strip(),
            color_hex=str(payload.get("color_hex") or "").strip(),
            color_hexes=payload.get("color_hexes") if isinstance(payload.get("color_hexes"), list) else [],
            transparency=str(payload.get("transparency") or "opaque").strip(),
            multi_color_direction=str(payload.get("multi_color_direction") or "").strip(),
            finish=str(payload.get("finish") or "").strip(),
            pattern=str(payload.get("pattern") or "").strip(),
            glow=bool(payload.get("glow")),
            diameter_mm=_parse_decimal(payload.get("diameter_mm", "1.75"), "diameter_mm", allow_none=False),
            density_g_cm3=_parse_decimal(payload.get("density_g_cm3"), "density_g_cm3"),
            nominal_weight_g=_parse_decimal(payload.get("nominal_weight_g"), "nominal_weight_g"),
            empty_spool_weight_g=_parse_decimal(payload.get("empty_spool_weight_g"), "empty_spool_weight_g"),
            nozzle_temp_min_c=payload.get("nozzle_temp_min_c") or None,
            nozzle_temp_max_c=payload.get("nozzle_temp_max_c") or None,
            bed_temp_min_c=payload.get("bed_temp_min_c") or None,
            bed_temp_max_c=payload.get("bed_temp_max_c") or None,
            drying_temp_c=payload.get("drying_temp_c") or None,
            drying_time_hours=_parse_decimal(payload.get("drying_time_hours"), "drying_time_hours"),
        )
        item.full_clean()
        item.save()
        item = FilamentProduct.objects.select_related(
            "manufacturer", "filament_manufacturer", "source"
        ).get(pk=item.pk)
        return JsonResponse({"item": _serialise_filament_product(item)}, status=201)
    except ValidationError as exc:
        return _validation_response(exc)
    except (ValueError, IntegrityError) as exc:
        return _error(str(exc))


@login_required
@require_http_methods(["PATCH", "DELETE"])
def printing_filament_detail(request, filament_id):
    item = FilamentProduct.objects.select_related(
        "manufacturer", "filament_manufacturer", "source"
    ).filter(pk=filament_id).first()
    if not item:
        return _error("Filament product not found.", status=404)
    if request.method == "DELETE":
        denied = _require_permission(request, "core.delete_filamentproduct")
        if denied:
            return denied
        try:
            item.delete()
            return JsonResponse({"deleted": True})
        except ProtectedError:
            return _error("This filament product is still used by one or more spools.", status=409)

    denied = _require_permission(request, "core.change_filamentproduct")
    if denied:
        return denied
    try:
        payload = _read_json(request)
        if any(key in payload for key in ["filament_manufacturer_id", "manufacturer_name", "manufacturer_id"]):
            item.filament_manufacturer = _resolve_filament_manufacturer(payload)
            item.manufacturer = None
        for field in ["name", "material", "color_name", "color_hex"]:
            if field in payload:
                setattr(item, field, str(payload.get(field) or "").strip())
        if "transparency" in payload:
            item.transparency = str(payload.get("transparency") or "opaque").strip()
        if "color_hexes" in payload:
            item.color_hexes = payload.get("color_hexes") if isinstance(payload.get("color_hexes"), list) else []
        for field in ["multi_color_direction", "finish", "pattern"]:
            if field in payload:
                setattr(item, field, str(payload.get(field) or "").strip())
        if "glow" in payload:
            item.glow = bool(payload.get("glow"))
        for field in ["diameter_mm", "density_g_cm3", "nominal_weight_g", "empty_spool_weight_g", "drying_time_hours"]:
            if field in payload:
                setattr(item, field, _parse_decimal(payload.get(field), field, allow_none=field != "diameter_mm"))
        for field in ["nozzle_temp_min_c", "nozzle_temp_max_c", "bed_temp_min_c", "bed_temp_max_c", "drying_temp_c"]:
            if field in payload:
                setattr(item, field, payload.get(field) or None)
        item.full_clean()
        item.save()
        return JsonResponse({"item": _serialise_filament_product(item)})
    except ValidationError as exc:
        return _validation_response(exc)


@login_required
@require_http_methods(["GET"])
def printing_filament_catalogue(request):
    try:
        query = str(request.GET.get("q") or "").strip()
        material = str(request.GET.get("material") or "").strip()
        manufacturer = str(request.GET.get("manufacturer") or "").strip()
        try:
            limit = min(max(int(request.GET.get("limit", 50)), 1), 100)
            offset = max(int(request.GET.get("offset", 0)), 0)
        except (TypeError, ValueError):
            return _error("Catalogue pagination values must be whole numbers.")
        return JsonResponse(search_spoolmandb(
            query=query,
            material=material,
            manufacturer=manufacturer,
            limit=limit,
            offset=offset,
        ))
    except FilamentCatalogueError as exc:
        return _error(str(exc), status=502)


@login_required
@require_http_methods(["POST"])
def printing_filament_catalogue_import(request):
    denied = _require_permission(request, "core.add_filamentproduct")
    if denied:
        return denied
    try:
        payload = _read_json(request)
        data = get_spoolmandb_item(payload.get("external_id"))

        manufacturer, _ = Manufacturer.objects.get_or_create(name=data["manufacturer"] or "Generic")
        source, _ = CatalogSource.objects.update_or_create(
            source_type="spoolmandb",
            external_id=data["external_id"],
            defaults={
                "name": f"SpoolmanDB — {data['manufacturer']} — {data['name']}"[:200],
                "url": data["source_url"],
                "raw_metadata": {
                    "license": data["source_license"],
                    "catalogue_id": data["external_id"],
                    "record": data["raw"],
                },
            },
        )

        existing = FilamentProduct.objects.filter(source=source).first()
        if existing:
            return JsonResponse({"item": _serialise_filament_product(existing), "created": False})

        existing = FilamentProduct.objects.filter(
            manufacturer=manufacturer,
            name=data["name"],
            material=data["material"],
            diameter_mm=_catalogue_decimal(data["diameter_mm"], "diameter_mm", 2),
            color_hex=data["color_hex"],
        ).first()

        defaults = {
            "source": source,
            "manufacturer": manufacturer,
            "name": data["name"],
            "material": data["material"],
            "color_name": data["color_name"],
            "color_hex": data["color_hex"],
            "color_hexes": data["color_hexes"],
            "transparency": data["transparency"],
            "multi_color_direction": data["multi_color_direction"],
            "finish": data["finish"],
            "pattern": data["pattern"],
            "glow": data["glow"],
            "diameter_mm": _catalogue_decimal(data["diameter_mm"], "diameter_mm", 2),
            "density_g_cm3": _catalogue_decimal(data["density_g_cm3"], "density_g_cm3", 3),
            "nominal_weight_g": _catalogue_decimal(data["nominal_weight_g"], "nominal_weight_g", 2),
            "empty_spool_weight_g": _catalogue_decimal(data["empty_spool_weight_g"], "empty_spool_weight_g", 2),
            "nozzle_temp_min_c": data["nozzle_temp_min_c"],
            "nozzle_temp_max_c": data["nozzle_temp_max_c"],
            "bed_temp_min_c": data["bed_temp_min_c"],
            "bed_temp_max_c": data["bed_temp_max_c"],
            "profile_data": {
                "source": "SpoolmanDB",
                "source_license": data["source_license"],
                "external_catalogue_id": data["external_id"],
                "spool_type": data["spool_type"],
                "raw_color_hexes": data["color_hexes"],
            },
        }

        if existing:
            changed = False
            if not existing.source:
                existing.source = source
                changed = True
            for field, value in defaults.items():
                if field in {"source", "manufacturer", "name", "material", "diameter_mm"}:
                    continue
                current = getattr(existing, field)
                if current in (None, "", [], {}) and value not in (None, "", [], {}):
                    setattr(existing, field, value)
                    changed = True
            if changed:
                existing.full_clean()
                existing.save()
            item = existing
            created = False
        else:
            item = FilamentProduct(**defaults)
            item.full_clean()
            item.save()
            created = True

        return JsonResponse({"item": _serialise_filament_product(item), "created": created}, status=201 if created else 200)
    except FilamentCatalogueError as exc:
        return _error(str(exc), status=502)
    except ValidationError as exc:
        return _validation_response(exc)
    except (ValueError, IntegrityError) as exc:
        return _error(str(exc))


@login_required
@require_http_methods(["GET", "POST"])
def printing_printers(request):
    if request.method == "GET":
        qs = Printer.objects.select_related("manufacturer").prefetch_related(
            "filament_slots__spool__filament__manufacturer"
        )
        return JsonResponse({"rows": [_serialise_printer(item) for item in qs]})

    denied = _require_permission(request, "core.add_printer")
    if denied:
        return denied
    try:
        payload = _read_json(request)
        manufacturer = None
        if payload.get("manufacturer_id"):
            manufacturer = Manufacturer.objects.filter(pk=payload["manufacturer_id"]).first()
            if not manufacturer:
                return _error("Selected manufacturer was not found.")
        item = Printer(
            name=str(payload.get("name") or "").strip(),
            manufacturer=manufacturer,
            model=str(payload.get("model") or "").strip(),
            serial_number=str(payload.get("serial_number") or "").strip(),
            location=str(payload.get("location") or "").strip(),
            build_volume_x_mm=_parse_decimal(payload.get("build_volume_x_mm"), "build_volume_x_mm"),
            build_volume_y_mm=_parse_decimal(payload.get("build_volume_y_mm"), "build_volume_y_mm"),
            build_volume_z_mm=_parse_decimal(payload.get("build_volume_z_mm"), "build_volume_z_mm"),
            nozzle_mm=_parse_decimal(payload.get("nozzle_mm", "0.4"), "nozzle_mm", allow_none=False),
            notes=str(payload.get("notes") or "").strip(),
        )
        item.full_clean()
        item.save()
        return JsonResponse({"item": _serialise_printer(item)}, status=201)
    except ValidationError as exc:
        return _validation_response(exc)


@login_required
@require_http_methods(["PATCH", "DELETE"])
def printing_printer_detail(request, printer_id):
    item = Printer.objects.select_related("manufacturer").prefetch_related(
        "filament_slots__spool__filament__manufacturer"
    ).filter(pk=printer_id).first()
    if not item:
        return _error("Printer not found.", status=404)
    if request.method == "DELETE":
        denied = _require_permission(request, "core.delete_printer")
        if denied:
            return denied
        try:
            item.delete()
            return JsonResponse({"deleted": True})
        except ProtectedError:
            return _error("This printer is referenced by print history and cannot be deleted.", status=409)

    denied = _require_permission(request, "core.change_printer")
    if denied:
        return denied
    try:
        payload = _read_json(request)
        if "manufacturer_id" in payload:
            manufacturer_id = payload.get("manufacturer_id")
            item.manufacturer = Manufacturer.objects.filter(pk=manufacturer_id).first() if manufacturer_id else None
            if manufacturer_id and not item.manufacturer:
                return _error("Selected manufacturer was not found.")
        for field in ["name", "model", "serial_number", "location", "notes"]:
            if field in payload:
                setattr(item, field, str(payload.get(field) or "").strip())
        for field in ["build_volume_x_mm", "build_volume_y_mm", "build_volume_z_mm", "nozzle_mm"]:
            if field in payload:
                setattr(item, field, _parse_decimal(payload.get(field), field, allow_none=field != "nozzle_mm"))
        item.full_clean()
        item.save()
        return JsonResponse({"item": _serialise_printer(item)})
    except ValidationError as exc:
        return _validation_response(exc)


@login_required
@require_http_methods(["GET", "POST"])
def printing_spools(request):
    if request.method == "GET":
        qs = Spool.objects.select_related("filament__manufacturer").prefetch_related(
            "external_links", "printer_slots__printer"
        )
        return JsonResponse({"rows": [_serialise_spool(item) for item in qs]})

    denied = _require_permission(request, "core.add_spool")
    if denied:
        return denied
    try:
        payload = _read_json(request)
        filament = FilamentProduct.objects.filter(pk=payload.get("filament_id")).first()
        if not filament:
            return _error("Choose a filament product.")
        item = Spool(
            spool_id=str(payload.get("spool_id") or "").strip(),
            filament=filament,
            initial_weight_g=_parse_decimal(payload.get("initial_weight_g"), "initial_weight_g"),
            remaining_weight_g=_parse_decimal(payload.get("remaining_weight_g"), "remaining_weight_g"),
            purchase_cost=_parse_decimal(payload.get("purchase_cost"), "purchase_cost"),
            currency=str(payload.get("currency") or settings.MAKERVAULT_CURRENCY).upper()[:3],
            location=str(payload.get("location") or "").strip(),
            status=str(payload.get("status") or "sealed"),
            opened_on=_parse_date(payload.get("opened_on"), "opened_on"),
            notes=str(payload.get("notes") or "").strip(),
        )
        item.full_clean()
        item.save()
        return JsonResponse({"item": _serialise_spool(item)}, status=201)
    except ValidationError as exc:
        return _validation_response(exc)
    except IntegrityError:
        return _error("Spool ID must be unique.")


@login_required
@require_http_methods(["PATCH", "DELETE"])
def printing_spool_detail(request, spool_id):
    item = Spool.objects.select_related("filament__manufacturer").prefetch_related(
        "external_links", "printer_slots__printer"
    ).filter(pk=spool_id).first()
    if not item:
        return _error("Spool not found.", status=404)
    if request.method == "DELETE":
        denied = _require_permission(request, "core.delete_spool")
        if denied:
            return denied
        try:
            item.delete()
            return JsonResponse({"deleted": True})
        except ProtectedError:
            return _error("This spool is referenced by print history and cannot be deleted.", status=409)

    denied = _require_permission(request, "core.change_spool")
    if denied:
        return denied
    try:
        payload = _read_json(request)
        if "filament_id" in payload:
            filament = FilamentProduct.objects.filter(pk=payload.get("filament_id")).first()
            if not filament:
                return _error("Choose a filament product.")
            item.filament = filament
        for field in ["spool_id", "status", "location", "currency", "notes"]:
            if field in payload:
                value = str(payload.get(field) or "").strip()
                setattr(item, field, value.upper()[:3] if field == "currency" else value)
        for field in ["initial_weight_g", "remaining_weight_g", "purchase_cost"]:
            if field in payload:
                setattr(item, field, _parse_decimal(payload.get(field), field))
        if "opened_on" in payload:
            item.opened_on = _parse_date(payload.get("opened_on"), "opened_on")
        item.full_clean()
        item.save()
        return JsonResponse({"item": _serialise_spool(item)})
    except ValidationError as exc:
        return _validation_response(exc)
    except IntegrityError:
        return _error("Spool ID must be unique.")


@login_required
@require_http_methods(["GET", "POST"])
def printing_models(request):
    if request.method == "GET":
        qs = Model3D.objects.select_related("project").prefetch_related(
            "revisions__assets__file_asset__project"
        )
        return JsonResponse({"rows": [_serialise_printing_model(item) for item in qs]})

    denied = _require_permission(request, "core.add_model3d")
    if denied:
        return denied
    try:
        payload = _read_json(request)
        project = None
        if payload.get("project_id"):
            project = Project.objects.filter(pk=payload["project_id"]).first()
            if not project:
                return _error("Selected project was not found.")
        item = Model3D(
            project=project,
            name=str(payload.get("name") or "").strip(),
            description=str(payload.get("description") or "").strip(),
            source_url=str(payload.get("source_url") or "").strip(),
            license=str(payload.get("license") or "").strip(),
            tags=_normalise_tags(payload.get("tags")),
        )
        item.full_clean()
        item.save()
        return JsonResponse({"item": _serialise_printing_model(item)}, status=201)
    except ValidationError as exc:
        return _validation_response(exc)


@login_required
@require_http_methods(["PATCH", "DELETE"])
def printing_model_detail(request, model_id):
    item = Model3D.objects.select_related("project").prefetch_related(
        "revisions__assets__file_asset__project"
    ).filter(pk=model_id).first()
    if not item:
        return _error("3D model not found.", status=404)
    if request.method == "DELETE":
        denied = _require_permission(request, "core.delete_model3d")
        if denied:
            return denied
        item.delete()
        return JsonResponse({"deleted": True})

    denied = _require_permission(request, "core.change_model3d")
    if denied:
        return denied
    try:
        payload = _read_json(request)
        if "project_id" in payload:
            project_id = payload.get("project_id")
            item.project = Project.objects.filter(pk=project_id).first() if project_id else None
            if project_id and not item.project:
                return _error("Selected project was not found.")
        for field in ["name", "description", "source_url", "license"]:
            if field in payload:
                setattr(item, field, str(payload.get(field) or "").strip())
        if "tags" in payload:
            item.tags = _normalise_tags(payload.get("tags"))
        item.full_clean()
        item.save()
        return JsonResponse({"item": _serialise_printing_model(item)})
    except ValidationError as exc:
        return _validation_response(exc)


@login_required
@require_http_methods(["POST"])
def printing_model_revisions(request, model_id):
    model = Model3D.objects.filter(pk=model_id).first()
    if not model:
        return _error("3D model not found.", status=404)
    denied = _require_permission(request, "core.change_model3d")
    if denied:
        return denied
    try:
        payload = _read_json(request)
        version = str(payload.get("version") or "").strip()
        if not version:
            return _error("Revision version is required.")
        revision = ModelRevision(
            model=model,
            version=version,
            notes=str(payload.get("notes") or "").strip(),
            source_url=str(payload.get("source_url") or "").strip(),
        )
        revision.full_clean()
        revision.save()
        model = Model3D.objects.select_related("project").prefetch_related(
            "revisions__assets__file_asset__project"
        ).get(pk=model.pk)
        return JsonResponse({"model": _serialise_printing_model(model)}, status=201)
    except ValidationError as exc:
        return _validation_response(exc)
    except IntegrityError:
        return _error("That revision version already exists for this model.")


@login_required
@require_http_methods(["PATCH", "DELETE"])
def printing_model_revision_detail(request, model_id, revision_id):
    model = Model3D.objects.filter(pk=model_id).first()
    if not model:
        return _error("3D model not found.", status=404)
    revision = ModelRevision.objects.filter(pk=revision_id, model=model).first()
    if not revision:
        return _error("Model revision not found.", status=404)
    denied = _require_permission(request, "core.change_model3d")
    if denied:
        return denied

    if request.method == "DELETE":
        if revision.prints.exists():
            return _error("This revision is referenced by print history and cannot be deleted.", status=409)
        revision.delete()
        return JsonResponse({"deleted": True})

    try:
        payload = _read_json(request)
        for field in ["version", "notes", "source_url"]:
            if field in payload:
                setattr(revision, field, str(payload.get(field) or "").strip())
        if not revision.version:
            return _error("Revision version is required.")
        revision.full_clean()
        revision.save()
        return JsonResponse({
            "revision": {
                "id": str(revision.id),
                "version": revision.version,
                "notes": revision.notes,
                "source_url": revision.source_url,
            }
        })
    except ValidationError as exc:
        return _validation_response(exc)
    except IntegrityError:
        return _error("That revision version already exists for this model.")


@login_required
@require_http_methods(["POST"])
def printing_revision_assets(request, model_id, revision_id):
    model = Model3D.objects.select_related("project").filter(pk=model_id).first()
    if not model:
        return _error("3D model not found.", status=404)
    revision = ModelRevision.objects.filter(pk=revision_id, model=model).first()
    if not revision:
        return _error("Model revision not found.", status=404)
    denied = _require_permission(request, "core.change_model3d")
    if denied:
        return denied

    try:
        payload = _read_json(request)
        asset = FileAsset.objects.select_related("project").filter(pk=payload.get("file_asset_id")).first()
        if not asset:
            return _error("Selected MakerVault file was not found.")
        if asset.category not in {"mesh", "slicer", "cad"}:
            return _error("Choose an STL/mesh, 3MF/slicer or CAD asset.")
        if model.project_id and asset.project_id and model.project_id != asset.project_id:
            return _error("This file belongs to a different project. Detach it or choose a matching project file first.")

        role = str(payload.get("role") or "model")
        if role not in dict(ModelRevisionAsset.ROLES):
            return _error("Unknown revision asset role.")
        is_primary = payload.get("is_primary") is True
        with transaction.atomic():
            if is_primary:
                revision.assets.filter(role=role, is_primary=True).update(is_primary=False)
            link = ModelRevisionAsset(
                revision=revision,
                file_asset=asset,
                role=role,
                is_primary=is_primary,
                notes=str(payload.get("notes") or "").strip(),
            )
            link.full_clean()
            link.save()

        model = Model3D.objects.select_related("project").prefetch_related(
            "revisions__assets__file_asset__project"
        ).get(pk=model.pk)
        return JsonResponse({"model": _serialise_printing_model(model)}, status=201)
    except ValidationError as exc:
        return _validation_response(exc)
    except IntegrityError:
        return _error("That file is already attached to this revision.")


@login_required
@require_http_methods(["DELETE"])
def printing_revision_asset_detail(request, model_id, revision_id, link_id):
    model = Model3D.objects.filter(pk=model_id).first()
    if not model:
        return _error("3D model not found.", status=404)
    revision = ModelRevision.objects.filter(pk=revision_id, model=model).first()
    if not revision:
        return _error("Model revision not found.", status=404)
    denied = _require_permission(request, "core.change_model3d")
    if denied:
        return denied
    link = ModelRevisionAsset.objects.filter(pk=link_id, revision=revision).first()
    if not link:
        return _error("Revision file link not found.", status=404)
    link.delete()
    return JsonResponse({"deleted": True})


def _parse_positive_int(value, field_name, *, allow_none=True):
    if value in (None, "") and allow_none:
        return None
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise ValidationError({field_name: "Enter a whole number."}) from exc
    if parsed <= 0:
        raise ValidationError({field_name: "Enter a number greater than zero."})
    return parsed


def _build_print_material_usage(job, printer, payload):
    spool = None
    filament = None
    slot = None

    if payload.get("spool_id"):
        spool = Spool.objects.select_related("filament").filter(pk=payload["spool_id"]).first()
        if not spool:
            raise ValidationError({"material_usages": "Selected spool was not found."})
        filament = spool.filament

    if payload.get("filament_id"):
        requested_filament = FilamentProduct.objects.filter(pk=payload["filament_id"]).first()
        if not requested_filament:
            raise ValidationError({"material_usages": "Selected filament was not found."})
        if spool and spool.filament_id != requested_filament.id:
            raise ValidationError({"material_usages": "Selected filament does not match the selected spool."})
        filament = requested_filament

    if payload.get("printer_slot_id"):
        slot = PrinterFilamentSlot.objects.select_related("spool__filament").filter(
            pk=payload["printer_slot_id"],
            printer=printer,
        ).first()
        if not slot:
            raise ValidationError({"material_usages": "Selected filament slot does not belong to this printer."})
        if not spool and slot.spool_id:
            spool = slot.spool
            filament = slot.spool.filament
        elif spool and slot.spool_id and slot.spool_id != spool.id:
            raise ValidationError({"material_usages": "Selected spool does not match the spool currently mapped to that slot."})

    if not spool and not filament:
        raise ValidationError({"material_usages": "Choose a spool, filament, or mapped printer slot for each material usage."})

    usage = PrintMaterialUsage(
        print_job=job,
        spool=spool,
        filament=filament,
        printer_slot=slot,
        used_g=_parse_decimal(payload.get("used_g", 0), "used_g", allow_none=False),
        waste_g=_parse_decimal(payload.get("waste_g", 0), "waste_g", allow_none=False),
        material_cost=_parse_decimal(payload.get("material_cost"), "material_cost"),
        currency=str(payload.get("currency") or settings.MAKERVAULT_CURRENCY).upper()[:3],
        notes=str(payload.get("notes") or "").strip(),
    )
    usage.full_clean()
    return usage


@login_required
@require_http_methods(["GET", "POST"])
def printing_jobs(request):
    if request.method == "GET":
        qs = PrintJob.objects.select_related(
            "printer", "project", "model_revision__model"
        ).prefetch_related(
            "material_usages__spool__filament__manufacturer",
            "material_usages__filament__manufacturer",
            "material_usages__printer_slot",
        )
        return JsonResponse({"rows": [_serialise_print_job(job) for job in qs[:2000]]})

    denied = _require_permission(request, "core.add_printjob")
    if denied:
        return denied

    try:
        payload = _read_json(request)
        printer = Printer.objects.filter(pk=payload.get("printer_id")).first()
        if not printer:
            return _error("Choose a printer.")

        project = None
        if payload.get("project_id"):
            project = Project.objects.filter(pk=payload["project_id"]).first()
            if not project:
                return _error("Selected project was not found.")

        revision = None
        if payload.get("model_revision_id"):
            revision = ModelRevision.objects.select_related("model").filter(pk=payload["model_revision_id"]).first()
            if not revision:
                return _error("Selected model revision was not found.")
            if project and revision.model.project_id and revision.model.project_id != project.id:
                return _error("Selected model revision belongs to a different project.")
            if not project and revision.model.project_id:
                project = revision.model.project

        status = str(payload.get("status") or "planned")
        if status not in dict(PrintJob.STATUS):
            return _error("Unknown print status.")

        material_payloads = payload.get("material_usages") or []
        if not isinstance(material_payloads, list):
            return _error("Material usages must be a list.")

        with transaction.atomic():
            job = PrintJob(
                model_revision=revision,
                project=project,
                printer=printer,
                status=status,
                quantity=_parse_positive_int(payload.get("quantity", 1), "quantity", allow_none=False),
                currency=str(payload.get("currency") or settings.MAKERVAULT_CURRENCY).upper()[:3],
                estimated_minutes=_parse_positive_int(payload.get("estimated_minutes"), "estimated_minutes"),
                actual_minutes=_parse_positive_int(payload.get("actual_minutes"), "actual_minutes"),
                layer_height_mm=_parse_decimal(payload.get("layer_height_mm"), "layer_height_mm"),
                nozzle_mm=_parse_decimal(payload.get("nozzle_mm"), "nozzle_mm"),
                slicer=str(payload.get("slicer") or "").strip(),
                settings=payload.get("settings") if isinstance(payload.get("settings"), dict) else {},
                notes=str(payload.get("notes") or "").strip(),
            )
            job.full_clean()
            job.save()

            for material_payload in material_payloads:
                if not isinstance(material_payload, dict):
                    raise ValidationError({"material_usages": "Each material usage must be an object."})
                _build_print_material_usage(job, printer, material_payload).save()

        job = PrintJob.objects.select_related(
            "printer", "project", "model_revision__model"
        ).prefetch_related(
            "material_usages__spool__filament__manufacturer",
            "material_usages__filament__manufacturer",
            "material_usages__printer_slot",
        ).get(pk=job.pk)
        return JsonResponse({"job": _serialise_print_job(job)}, status=201)
    except ValidationError as exc:
        return _validation_response(exc)


@login_required
@require_http_methods(["PATCH", "DELETE"])
def printing_job_detail(request, job_id):
    job = PrintJob.objects.select_related(
        "printer", "project", "model_revision__model"
    ).prefetch_related(
        "material_usages__spool__filament__manufacturer",
        "material_usages__filament__manufacturer",
        "material_usages__printer_slot",
    ).filter(pk=job_id).first()
    if not job:
        return _error("Print job not found.", status=404)

    if request.method == "DELETE":
        denied = _require_permission(request, "core.delete_printjob")
        if denied:
            return denied
        job.delete()
        return JsonResponse({"deleted": True})

    denied = _require_permission(request, "core.change_printjob")
    if denied:
        return denied
    try:
        payload = _read_json(request)
        if "status" in payload:
            status = str(payload.get("status") or "")
            if status not in dict(PrintJob.STATUS):
                return _error("Unknown print status.")
            job.status = status
        if "quantity" in payload:
            job.quantity = _parse_positive_int(payload.get("quantity"), "quantity", allow_none=False)
        for field in ["estimated_minutes", "actual_minutes"]:
            if field in payload:
                setattr(job, field, _parse_positive_int(payload.get(field), field))
        for field in ["layer_height_mm", "nozzle_mm"]:
            if field in payload:
                setattr(job, field, _parse_decimal(payload.get(field), field))
        for field in ["slicer", "notes"]:
            if field in payload:
                setattr(job, field, str(payload.get(field) or "").strip())
        job.full_clean()
        job.save()
        return JsonResponse({"job": _serialise_print_job(job)})
    except ValidationError as exc:
        return _validation_response(exc)


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
            "add_project": request.user.has_perm("core.add_project"),
            "change_project": request.user.has_perm("core.change_project"),
            "delete_project": request.user.has_perm("core.delete_project"),
            "add_file": request.user.has_perm("core.add_fileasset"),
            "change_file": request.user.has_perm("core.change_fileasset"),
            "add_printer": request.user.has_perm("core.add_printer"),
            "change_printer": request.user.has_perm("core.change_printer"),
            "add_filament": request.user.has_perm("core.add_filamentproduct"),
            "change_filament": request.user.has_perm("core.change_filamentproduct"),
            "add_spool": request.user.has_perm("core.add_spool"),
            "change_spool": request.user.has_perm("core.change_spool"),
            "add_model3d": request.user.has_perm("core.add_model3d"),
            "change_model3d": request.user.has_perm("core.change_model3d"),
            "add_printjob": request.user.has_perm("core.add_printjob"),
            "change_printjob": request.user.has_perm("core.change_printjob"),
        },
        "importers": ["ESPBoards.dev"],
    })
