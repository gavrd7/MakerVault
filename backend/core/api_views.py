import hashlib
import json
import re
from pathlib import Path
from datetime import timedelta
from decimal import Decimal, InvalidOperation

from django.conf import settings
from django.contrib.auth import get_user_model
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
from .catalogue_coverage import catalogue_coverage_summary
from .filament_catalogue import (
    FilamentCatalogueError,
    get_spoolmandb_item,
    search_spoolmandb,
    spoolmandb_meta,
)
from .printing_catalogue_seed import COMMON_FILAMENT_MATERIALS
from .model_analysis import ModelAnalysisError, analyse_file_asset
from .printing_integrations import PrintingIntegrationError, probe_simplyprint, probe_spoolman
from .printer_connectivity import (
    ADAPTERS as PRINTER_ADAPTERS,
    PrinterConnectionError,
    adapter_catalogue,
    normalise_printer_endpoint,
    poll_connection,
)
from .printing_sync import PrintingSyncError, next_spool_id, resolve_spoolman_review, sync_printing_integration
from .tasks import queue_catalogue_maintenance_now
from .storage_usage import StorageQuotaExceeded, ensure_storage_capacity, storage_settings, storage_summary
from .user_admin import admin_user_summary, purge_user_private_data
from .private_storage import private_storage_key_status
from .search_service import run_search
from .wiring import normalise_wiring, serialise_wiring_diagram
from .maker_tags import (
    TAG_TECHNOLOGIES,
    resolve_tag_target,
    serialise_tag,
    tag_target_options,
)
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
    MakerTag,
    MakerTagEvent,
    Manufacturer,
    Model3D,
    ModelRevision,
    ModelRevisionAsset,
    Printer,
    PrinterConnection,
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
    WiringDiagram,
    ExternalPrinterLink,
    ExternalSpoolLink,
)


def _error(message, status=400, fields=None):
    payload = {"error": message}
    if fields:
        payload["fields"] = fields
    return JsonResponse(payload, status=status)


def _storage_quota_response(request, exc):
    summary = storage_summary(request.user)
    return JsonResponse({
        "error": "This upload would exceed your MakerVault storage quota.",
        "code": "storage_quota_exceeded",
        "requested_growth_bytes": exc.requested_bytes,
        "projected_bytes": exc.projected_bytes,
        "storage": summary,
    }, status=413)


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


def _record_tag_event(tag, user, event_type, summary, details=None):
    MakerTagEvent.objects.create(
        tag=tag,
        changed_by=user,
        event_type=event_type,
        summary=summary,
        details=details or {},
    )


def _sync_rfid_tag_to_spool(tag, *, previous=None):
    """Keep the legacy spool RFID field as a compatibility mirror for RFID Maker Tags."""
    if previous and previous.get("kind") == "rfid" and previous.get("target_type") == "spool":
        old_spool = Spool.objects.filter(
            owner=tag.owner,
            pk=previous.get("target_id"),
        ).first()
        if old_spool and old_spool.rfid_uid == previous.get("code") and (
            tag.kind != "rfid"
            or tag.target_type != "spool"
            or str(tag.target_id) != str(previous.get("target_id"))
            or tag.code != previous.get("code")
        ):
            old_spool.rfid_uid = ""
            old_spool.save(update_fields=["rfid_uid", "updated_at"])

    if tag.kind != "rfid" or tag.target_type != "spool" or not MakerTag.is_uid_like(tag.code):
        return

    spool = Spool.objects.filter(owner=tag.owner, pk=tag.target_id).first()
    if not spool:
        return
    existing = str(spool.rfid_uid or "").strip().upper()
    if existing and existing != tag.code:
        raise ValidationError({
            "code": "This spool already has a different RFID UID. Use its existing RFID identity or clear it first."
        })
    if existing != tag.code:
        spool.rfid_uid = tag.code
        spool.save(update_fields=["rfid_uid", "updated_at"])


@login_required
@require_http_methods(["GET", "POST"])
def wiring_lab_diagrams(request):
    """Standalone wiring workspaces for experimentation before project assignment."""
    if request.method == "GET":
        rows = WiringDiagram.objects.filter(owner=request.user, project__isnull=True)
        return JsonResponse({"rows": [serialise_wiring_diagram(item) for item in rows]})

    denied = _require_permission(request, "core.add_wiringdiagram")
    if denied:
        return denied
    try:
        payload = _read_json(request)
        name = str(payload.get("name") or "").strip()
        if not name:
            raise ValidationError({"name": "Diagram name is required."})
        nodes, connections, canvas = normalise_wiring(
            request.user,
            payload.get("nodes") or [],
            payload.get("connections") or [],
            payload.get("canvas") or {},
        )
        diagram = WiringDiagram(
            owner=request.user,
            project=None,
            name=name,
            description=str(payload.get("description") or "").strip(),
            nodes=nodes,
            connections=connections,
            canvas=canvas,
        )
        diagram.full_clean()
        diagram.save()
        return JsonResponse({"item": serialise_wiring_diagram(diagram, detailed=True)}, status=201)
    except ValidationError as exc:
        return _validation_response(exc)
    except IntegrityError:
        return _error("A standalone wiring diagram with that name already exists.")


@login_required
@require_http_methods(["GET", "PATCH", "DELETE"])
def wiring_lab_diagram_detail(request, diagram_id):
    diagram = WiringDiagram.objects.filter(owner=request.user, project__isnull=True, pk=diagram_id).first()
    if not diagram:
        return _error("Standalone wiring diagram not found.", status=404)

    if request.method == "GET":
        return JsonResponse({"item": serialise_wiring_diagram(diagram, detailed=True)})
    if request.method == "DELETE":
        denied = _require_permission(request, "core.delete_wiringdiagram")
        if denied:
            return denied
        diagram.delete()
        return JsonResponse({"deleted": True})

    denied = _require_permission(request, "core.change_wiringdiagram")
    if denied:
        return denied
    try:
        payload = _read_json(request)
        if "name" in payload:
            name = str(payload.get("name") or "").strip()
            if not name:
                raise ValidationError({"name": "Diagram name is required."})
            diagram.name = name
        if "description" in payload:
            diagram.description = str(payload.get("description") or "").strip()
        if any(key in payload for key in ("nodes", "connections", "canvas")):
            nodes, connections, canvas = normalise_wiring(
                request.user,
                payload.get("nodes", diagram.nodes),
                payload.get("connections", diagram.connections),
                payload.get("canvas", diagram.canvas),
            )
            diagram.nodes = nodes
            diagram.connections = connections
            diagram.canvas = canvas
            diagram.revision += 1
        diagram.full_clean()
        diagram.save()
        return JsonResponse({"item": serialise_wiring_diagram(diagram, detailed=True)})
    except ValidationError as exc:
        return _validation_response(exc)
    except IntegrityError:
        return _error("A standalone wiring diagram with that name already exists.")


@login_required
@require_http_methods(["POST"])
def wiring_lab_assign_project(request, diagram_id):
    denied = _require_permission(request, "core.change_wiringdiagram")
    if denied:
        return denied
    diagram = WiringDiagram.objects.filter(owner=request.user, project__isnull=True, pk=diagram_id).first()
    if not diagram:
        return _error("Standalone wiring diagram not found.", status=404)
    try:
        payload = _read_json(request)
        project = Project.objects.filter(owner=request.user, pk=payload.get("project_id")).first()
        if not project:
            raise ValidationError({"project_id": "Choose one of your projects."})
        if WiringDiagram.objects.filter(project=project, name=diagram.name).exclude(pk=diagram.pk).exists():
            raise ValidationError({"project_id": "That project already has a wiring diagram with this name."})
        diagram.project = project
        diagram.full_clean()
        diagram.save(update_fields=["project", "updated_at"])
        return JsonResponse({"item": serialise_wiring_diagram(diagram, detailed=True)})
    except ValidationError as exc:
        return _validation_response(exc)


@login_required
@require_http_methods(["GET", "POST"])
def project_wiring_diagrams(request, project_id):
    project = Project.objects.filter(owner=request.user, pk=project_id).first()
    if not project:
        return _error("Project not found.", status=404)

    if request.method == "GET":
        rows = WiringDiagram.objects.filter(owner=request.user, project=project)
        return JsonResponse({"rows": [serialise_wiring_diagram(item) for item in rows]})

    denied = _require_permission(request, "core.add_wiringdiagram")
    if denied:
        return denied
    try:
        payload = _read_json(request)
        name = str(payload.get("name") or "").strip()
        if not name:
            raise ValidationError({"name": "Diagram name is required."})
        nodes, connections, canvas = normalise_wiring(
            request.user,
            payload.get("nodes") or [],
            payload.get("connections") or [],
            payload.get("canvas") or {},
        )
        diagram = WiringDiagram(
            owner=request.user,
            project=project,
            name=name,
            description=str(payload.get("description") or "").strip(),
            nodes=nodes,
            connections=connections,
            canvas=canvas,
        )
        diagram.full_clean()
        diagram.save()
        return JsonResponse({"item": serialise_wiring_diagram(diagram, detailed=True)}, status=201)
    except ValidationError as exc:
        return _validation_response(exc)
    except IntegrityError:
        return _error("A wiring diagram with that name already exists in this project.")


@login_required
@require_http_methods(["GET", "PATCH", "DELETE"])
def project_wiring_diagram_detail(request, project_id, diagram_id):
    diagram = WiringDiagram.objects.filter(
        owner=request.user,
        project_id=project_id,
        pk=diagram_id,
    ).select_related("project").first()
    if not diagram:
        return _error("Wiring diagram not found.", status=404)

    if request.method == "GET":
        return JsonResponse({"item": serialise_wiring_diagram(diagram, detailed=True)})

    if request.method == "DELETE":
        denied = _require_permission(request, "core.delete_wiringdiagram")
        if denied:
            return denied
        diagram.delete()
        return JsonResponse({"deleted": True})

    denied = _require_permission(request, "core.change_wiringdiagram")
    if denied:
        return denied
    try:
        payload = _read_json(request)
        if "name" in payload:
            name = str(payload.get("name") or "").strip()
            if not name:
                raise ValidationError({"name": "Diagram name is required."})
            diagram.name = name
        if "description" in payload:
            diagram.description = str(payload.get("description") or "").strip()

        structure_changed = any(key in payload for key in ("nodes", "connections", "canvas"))
        if structure_changed:
            nodes, connections, canvas = normalise_wiring(
                request.user,
                payload.get("nodes", diagram.nodes),
                payload.get("connections", diagram.connections),
                payload.get("canvas", diagram.canvas),
            )
            diagram.nodes = nodes
            diagram.connections = connections
            diagram.canvas = canvas
            diagram.revision += 1

        diagram.full_clean()
        diagram.save()
        return JsonResponse({"item": serialise_wiring_diagram(diagram, detailed=True)})
    except ValidationError as exc:
        return _validation_response(exc)
    except IntegrityError:
        return _error("A wiring diagram with that name already exists in this project.")


@login_required
@require_http_methods(["GET", "POST"])
def maker_tags(request):
    if request.method == "GET":
        qs = MakerTag.objects.filter(owner=request.user)
        kind = str(request.GET.get("kind") or "").strip().lower()
        status = str(request.GET.get("status") or "").strip().lower()
        target_type = str(request.GET.get("target_type") or "").strip().lower()
        if kind:
            qs = qs.filter(kind=kind)
        if status:
            qs = qs.filter(status=status)
        if target_type:
            qs = qs.filter(target_type=target_type)
        return JsonResponse({
            "rows": [serialise_tag(tag) for tag in qs[:5000]],
            "targets": tag_target_options(request.user),
            "kinds": [{"value": value, "label": label} for value, label in MakerTag.KINDS],
            "technologies": [{"value": value, "label": label} for value, label in TAG_TECHNOLOGIES],
            "target_types": [{"value": value, "label": label} for value, label in MakerTag.TARGET_TYPES],
        })

    denied = _require_permission(request, "core.add_makertag")
    if denied:
        return denied
    try:
        payload = _read_json(request)
        kind = str(payload.get("kind") or "qr").strip().lower()
        if kind not in dict(MakerTag.KINDS):
            raise ValidationError({"kind": "Choose a supported tag type."})
        target_type = str(payload.get("target_type") or "").strip().lower()
        target = resolve_tag_target(request.user, target_type, payload.get("target_id"))

        tag = MakerTag(
            owner=request.user,
            kind=kind,
            code=str(payload.get("code") or "").strip(),
            label=str(payload.get("label") or "").strip(),
            target_type=target_type,
            target_id=target.pk,
            notes=str(payload.get("notes") or "").strip(),
            metadata=payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {},
        )
        if kind == "qr" and not tag.code:
            tag.code = f"MV-{tag.public_token.hex[:16].upper()}"
        if kind == "rfid" and target_type == "spool":
            existing = str(target.rfid_uid or "").strip().upper()
            submitted = MakerTag.normalise_code(kind, tag.code)
            if existing and submitted and MakerTag.is_uid_like(submitted) and existing != submitted:
                raise ValidationError({
                    "code": "This spool already has a different RFID UID. Use the existing RFID value."
                })
            if existing and not submitted:
                tag.code = existing

        with transaction.atomic():
            tag.full_clean()
            tag.save()
            _sync_rfid_tag_to_spool(tag)
            _record_tag_event(
                tag,
                request.user,
                "created",
                f"Created {tag.get_kind_display()} identity and assigned it to {tag.target_type}.",
                {"target_type": tag.target_type, "target_id": str(tag.target_id)},
            )
        return JsonResponse({"item": serialise_tag(tag, include_events=True)}, status=201)
    except ValidationError as exc:
        return _validation_response(exc)
    except (ValueError, IntegrityError) as exc:
        return _error(str(exc))


@login_required
@require_http_methods(["GET", "PATCH"])
def maker_tag_detail(request, tag_id):
    tag = MakerTag.objects.filter(owner=request.user, pk=tag_id).first()
    if not tag:
        return _error("Maker Tag not found.", status=404)
    if request.method == "GET":
        return JsonResponse({"item": serialise_tag(tag, include_events=True)})

    denied = _require_permission(request, "core.change_makertag")
    if denied:
        return denied
    try:
        payload = _read_json(request)
        previous = {
            "kind": tag.kind,
            "code": tag.code,
            "target_type": tag.target_type,
            "target_id": str(tag.target_id),
            "status": tag.status,
        }

        if "kind" in payload:
            kind = str(payload.get("kind") or "").strip().lower()
            if kind not in dict(MakerTag.KINDS):
                raise ValidationError({"kind": "Choose a supported tag type."})
            tag.kind = kind
        if "code" in payload:
            tag.code = str(payload.get("code") or "").strip()
        if "label" in payload:
            tag.label = str(payload.get("label") or "").strip()
        if "notes" in payload:
            tag.notes = str(payload.get("notes") or "").strip()
        if "metadata" in payload and isinstance(payload.get("metadata"), dict):
            tag.metadata = payload["metadata"]

        target_type = str(payload.get("target_type") or tag.target_type).strip().lower()
        target_id = payload.get("target_id") or tag.target_id
        target = resolve_tag_target(request.user, target_type, target_id)
        tag.target_type = target_type
        tag.target_id = target.pk

        if tag.kind == "qr" and not str(tag.code or "").strip():
            tag.code = f"MV-{tag.public_token.hex[:16].upper()}"

        requested_status = str(payload.get("status") or tag.status).strip().lower()
        if requested_status not in dict(MakerTag.STATUSES):
            raise ValidationError({"status": "Choose Active or Retired."})
        if requested_status == "retired" and tag.status != "retired":
            tag.retired_at = timezone.now()
        elif requested_status == "active" and tag.status == "retired":
            tag.retired_at = None
        tag.status = requested_status

        if tag.kind == "rfid" and tag.target_type == "spool":
            existing = str(target.rfid_uid or "").strip().upper()
            submitted = MakerTag.normalise_code(tag.kind, tag.code)
            if existing and MakerTag.is_uid_like(submitted) and existing not in {submitted, previous.get("code", "")}:
                raise ValidationError({
                    "code": "The target spool already has a different RFID UID."
                })

        with transaction.atomic():
            tag.full_clean()
            tag.save()
            _sync_rfid_tag_to_spool(tag, previous=previous)

            reassigned = (
                previous["target_type"] != tag.target_type
                or previous["target_id"] != str(tag.target_id)
            )
            if previous["status"] != tag.status:
                event_type = "retired" if tag.status == "retired" else "reactivated"
                summary = f"{tag.get_status_display()} Maker Tag."
            elif reassigned:
                event_type = "reassigned"
                summary = f"Reassigned Maker Tag to {tag.target_type}."
            else:
                event_type = "updated"
                summary = "Updated Maker Tag details."
            _record_tag_event(tag, request.user, event_type, summary, {
                "previous": previous,
                "target_type": tag.target_type,
                "target_id": str(tag.target_id),
            })

        return JsonResponse({"item": serialise_tag(tag, include_events=True)})
    except ValidationError as exc:
        return _validation_response(exc)
    except (ValueError, IntegrityError) as exc:
        return _error(str(exc))


@login_required
@require_http_methods(["GET"])
def maker_tag_resolve_token(request, public_token):
    tag = MakerTag.objects.filter(
        owner=request.user,
        public_token=public_token,
        status="active",
    ).first()
    if not tag:
        return _error("Active Maker Tag not found.", status=404)
    return JsonResponse({"item": serialise_tag(tag, include_events=True)})


@login_required
@require_http_methods(["GET"])
def maker_tag_resolve_code(request):
    kind = str(request.GET.get("kind") or "").strip().lower()
    raw_code = str(request.GET.get("code") or "").strip()
    if not raw_code:
        return _error("Provide a tag identity code.")

    if kind == "auto":
        matches = []
        for candidate_kind, _label in MakerTag.KINDS:
            code = MakerTag.normalise_code(candidate_kind, raw_code)
            tag = MakerTag.objects.filter(
                owner=request.user,
                kind=candidate_kind,
                code=code,
                status="active",
            ).first()
            if tag and tag.pk not in {item.pk for item in matches}:
                matches.append(tag)
        if not matches:
            return _error("Active Maker Tag not found.", status=404)
        if len(matches) > 1:
            return _error("More than one tag matches this reader value. Choose NFC, RFID or QR explicitly.")
        return JsonResponse({"item": serialise_tag(matches[0], include_events=True)})

    code = MakerTag.normalise_code(kind, raw_code)
    if kind not in dict(MakerTag.KINDS) or not code:
        return _error("Provide a supported tag type and identity code.")
    tag = MakerTag.objects.filter(
        owner=request.user,
        kind=kind,
        code=code,
        status="active",
    ).first()
    if not tag:
        return _error("Active Maker Tag not found.", status=404)
    return JsonResponse({"item": serialise_tag(tag, include_events=True)})


@login_required
@require_http_methods(["GET"])
def universal_search(request):
    query = str(request.GET.get("q") or "").strip()
    raw_types = str(request.GET.get("types") or "").strip()
    selected_types = [item.strip() for item in raw_types.split(",") if item.strip()] if raw_types else None
    sort = str(request.GET.get("sort") or "relevance").strip().lower()
    if sort not in {"relevance", "name", "newest", "oldest"}:
        sort = "relevance"
    try:
        limit = min(max(int(request.GET.get("limit") or 25), 1), 100)
    except (TypeError, ValueError):
        limit = 25

    return JsonResponse(run_search(
        request.user,
        query=query,
        selected_types=selected_types,
        sort=sort,
        limit_per_type=limit,
        project_id=str(request.GET.get("project") or "").strip() or None,
        status=str(request.GET.get("status") or "").strip() or None,
        manufacturer=str(request.GET.get("manufacturer") or "").strip() or None,
        updated_after=str(request.GET.get("updated_after") or "").strip() or None,
        updated_before=str(request.GET.get("updated_before") or "").strip() or None,
    ))


def _image_url(obj, image_field="image", metadata_field=None):
    image = getattr(obj, image_field, None)
    if image:
        try:
            return image.url
        except ValueError:
            pass
    if metadata_field:
        metadata = getattr(obj, metadata_field, {}) or {}
    else:
        metadata = getattr(obj, "specifications", None)
        if metadata is None:
            metadata = getattr(obj, "image_metadata", {})
        metadata = metadata or {}
    return metadata.get("external_image_url") or ""


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
        # Pinout is compact structured catalogue data used by the wiring editor.
        # Include it in catalogue rows so a newly-added node can offer pin choices
        # immediately, before the diagram's first save/reload.
        "pinout": board.pinout,
        # Board type is needed by the catalogue list/filter and wiring picker.
        # Avoid shipping the full specifications object for every catalogue row.
        "board_type": (board.specifications or {}).get("board_type", "microcontroller"),
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


def _inventory_free_quantity(item):
    """Return stock that is genuinely free for a new allocation."""
    if item.status != "available" or item.project_id:
        return Decimal("0")
    allocated = _inventory_allocated_quantity(item)
    return max((item.quantity or Decimal("0")) - allocated, Decimal("0"))


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
    available = _inventory_free_quantity(item)
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
    inventory_available = _inventory_free_quantity(inventory)
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
        "inventory_item__component",
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
        "board__manufacturer", "component__category"
    ).prefetch_related(
        "allocations__inventory_item__board__manufacturer",
        "allocations__inventory_item__component",
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
        "supersedes_id": str(asset.supersedes_id) if asset.supersedes_id else "",
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
    for item in project.inventory_items.filter(owner=project.owner):
        if item.purchase_price is not None:
            total += item.purchase_price * item.quantity
            currency = item.currency or currency
    return float(total), currency


def _serialise_project(project, detailed=False):
    gallery_qs = project.files.filter(owner=project.owner, category="image").order_by("-created_at")
    asset_qs = project.files.filter(owner=project.owner).exclude(category="image").filter(superseded_by__isnull=True).order_by("category", "-created_at")
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
        "inventory_count": project.inventory_items.filter(owner=project.owner).count(),
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
            "inventory": [_serialise_inventory(item) for item in project.inventory_items.filter(owner=project.owner).select_related(
                "board__manufacturer", "project"
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


def _resolve_printing_location(location_id, owner, field_name="location_id"):
    if not location_id:
        return None
    location = PrintingLocation.objects.filter(owner=owner, pk=location_id).first()
    if not location:
        raise ValidationError({field_name: "Selected location was not found."})
    return location


def _resolve_printer_catalogue(payload):
    catalog_model = None
    if payload.get("catalog_model_id"):
        catalog_model = PrinterCatalogModel.objects.select_related("manufacturer").filter(
            pk=payload.get("catalog_model_id")
        ).first()
        if not catalog_model:
            raise ValidationError({"catalog_model_id": "Selected printer model was not found."})
        return catalog_model.manufacturer, catalog_model

    manufacturer = None
    manufacturer_id = payload.get("printer_manufacturer_id") or payload.get("manufacturer_id")
    if manufacturer_id:
        manufacturer = PrinterManufacturer.objects.filter(pk=manufacturer_id).first()
        if not manufacturer:
            raise ValidationError({"printer_manufacturer_id": "Selected printer manufacturer was not found."})
    else:
        manufacturer_name = str(payload.get("manufacturer_name") or "").strip()
        if manufacturer_name:
            manufacturer, _ = PrinterManufacturer.objects.get_or_create(name=manufacturer_name)

    return manufacturer, None


def _next_inventory_id(owner, item_type):
    prefix = {
        "board": "MCU",
        "component": "CMP",
        "tool": "AST",
        "printed_part": "PRT",
        "other": "OTH",
    }.get(item_type, "INV")
    highest = 0
    for existing in InventoryItem.objects.filter(owner=owner, inventory_id__startswith=f"{prefix}-").values_list("inventory_id", flat=True):
        match = re.fullmatch(rf"{re.escape(prefix)}-(\d+)", existing or "")
        if match:
            highest = max(highest, int(match.group(1)))
    candidate = highest + 1
    while InventoryItem.objects.filter(owner=owner, inventory_id=f"{prefix}-{candidate:04d}").exists():
        candidate += 1
    return f"{prefix}-{candidate:04d}"


@login_required
@require_http_methods(["GET"])
def user_storage(request):
    """Return the authenticated user's logical storage usage and effective quota."""
    return JsonResponse(storage_summary(request.user))


def _superuser_required(request):
    if request.user.is_superuser:
        return None
    return _error("Superuser access is required.", status=403)


def _quota_bytes(value, field_name="quota_bytes"):
    try:
        result = int(value)
    except (TypeError, ValueError) as exc:
        raise ValidationError({field_name: "Enter a whole number of bytes."}) from exc
    if result < 0:
        raise ValidationError({field_name: "Storage quota cannot be negative."})
    return result


@login_required
@require_http_methods(["GET", "PATCH"])
def admin_storage_policy(request):
    denied = _superuser_required(request)
    if denied:
        return denied
    policy = storage_settings()
    if request.method == "PATCH":
        try:
            payload = _read_json(request)
            mode = str(payload.get("mode") or ("unlimited" if policy.default_quota_unlimited else "limited")).strip().lower()
            if mode not in {"limited", "unlimited"}:
                return _error("Unknown instance storage policy.")
            policy.default_quota_unlimited = mode == "unlimited"
            if "default_quota_bytes" in payload:
                policy.default_quota_bytes = _quota_bytes(payload.get("default_quota_bytes"), "default_quota_bytes")
            policy.full_clean()
            policy.save()
        except ValidationError as exc:
            return _validation_response(exc)
    return JsonResponse({
        "policy": {
            "mode": "unlimited" if policy.default_quota_unlimited else "limited",
            "default_quota_bytes": int(policy.default_quota_bytes),
            "encryption": private_storage_key_status(),
        }
    })


@login_required
@require_http_methods(["GET"])
def admin_users(request):
    denied = _superuser_required(request)
    if denied:
        return denied
    User = get_user_model()
    rows = [admin_user_summary(user) for user in User.objects.order_by("username")]
    return JsonResponse({"rows": rows})


@login_required
@require_http_methods(["PATCH"])
def admin_user_detail(request, user_id):
    denied = _superuser_required(request)
    if denied:
        return denied
    User = get_user_model()
    target = User.objects.filter(pk=user_id).first()
    if not target:
        return _error("User not found.", status=404)

    try:
        payload = _read_json(request)
        if "is_active" in payload:
            active = bool(payload.get("is_active"))
            if target.pk == request.user.pk and not active:
                return _error("You cannot disable the account you are currently using.")
            if target.is_superuser and target.is_active and not active:
                active_superusers = User.objects.filter(is_superuser=True, is_active=True).count()
                if active_superusers <= 1:
                    return _error("The last active superuser cannot be disabled.")
            target.is_active = active
            target.save(update_fields=["is_active"])

        if "quota_mode" in payload:
            mode = str(payload.get("quota_mode") or "").strip().lower()
            if mode not in {"default", "override", "unlimited"}:
                return _error("Unknown user quota mode.")
            from .models import UserStorageProfile
            profile, _ = UserStorageProfile.objects.get_or_create(user=target)
            if mode == "default":
                profile.quota_unlimited = False
                profile.quota_override_bytes = None
            elif mode == "unlimited":
                profile.quota_unlimited = True
                profile.quota_override_bytes = None
            else:
                profile.quota_unlimited = False
                profile.quota_override_bytes = _quota_bytes(payload.get("quota_bytes"))
            profile.full_clean()
            profile.save(update_fields=["quota_unlimited", "quota_override_bytes", "updated_at"])

        return JsonResponse({"item": admin_user_summary(target)})
    except ValidationError as exc:
        return _validation_response(exc)


@login_required
@require_http_methods(["POST"])
def admin_user_purge(request, user_id):
    denied = _superuser_required(request)
    if denied:
        return denied
    User = get_user_model()
    target = User.objects.filter(pk=user_id).first()
    if not target:
        return _error("User not found.", status=404)
    if target.pk == request.user.pk:
        return _error("You cannot purge the account you are currently using.")
    try:
        payload = _read_json(request)
    except ValueError as exc:
        return _error(str(exc))
    if str(payload.get("confirm") or "") != target.get_username():
        return _error("Type the exact username to confirm this destructive action.")
    result = purge_user_private_data(target)
    return JsonResponse({"result": result, "item": admin_user_summary(target)})


@login_required
@require_http_methods(["DELETE"])
def admin_user_delete(request, user_id):
    denied = _superuser_required(request)
    if denied:
        return denied
    User = get_user_model()
    target = User.objects.filter(pk=user_id).first()
    if not target:
        return _error("User not found.", status=404)
    if target.pk == request.user.pk:
        return _error("You cannot delete the account you are currently using.")
    if target.is_superuser and User.objects.filter(is_superuser=True).count() <= 1:
        return _error("The last superuser account cannot be deleted.")
    try:
        payload = _read_json(request)
    except ValueError as exc:
        return _error(str(exc))
    if str(payload.get("confirm") or "") != target.get_username():
        return _error("Type the exact username to confirm account deletion.")
    purge_user_private_data(target)
    username = target.get_username()
    target.delete()
    return JsonResponse({"deleted": True, "username": username})


@login_required
@require_http_methods(["GET"])
def dashboard(request):
    data = {
        "inventory_total": InventoryItem.objects.filter(owner=request.user).count(),
        "inventory_available": InventoryItem.objects.filter(owner=request.user).filter(status="available").count(),
        "inventory_in_use": InventoryItem.objects.filter(owner=request.user).filter(status="in_use").count(),
        "projects_active": Project.objects.filter(owner=request.user).filter(status="active").count(),
        "projects_total": Project.objects.filter(owner=request.user).count(),
        "board_models": BoardModel.objects.count(),
        "component_models": ComponentModel.objects.count(),
        "filament_products": FilamentProduct.objects.count(),
        "spools": Spool.objects.filter(owner=request.user).count(),
        "printers": Printer.objects.filter(owner=request.user).count(),
        "models_3d": Model3D.objects.filter(owner=request.user).count(),
        "maker_tags": MakerTag.objects.filter(owner=request.user, status="active").count(),
    }
    return JsonResponse(data)


def _inventory_unit_count(value):
    try:
        parsed = Decimal(str(value if value not in (None, "") else 1))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValidationError({"quantity": "Enter a whole number of items."}) from exc
    if parsed != parsed.to_integral_value() or parsed < 1:
        raise ValidationError({"quantity": "Inventory quantity must be a whole number of at least 1."})
    if parsed > 500:
        raise ValidationError({"quantity": "Add no more than 500 inventory items at once."})
    return int(parsed)


@login_required
@require_http_methods(["GET", "POST"])
def inventory(request):
    if request.method == "GET":
        qs = InventoryItem.objects.filter(owner=request.user).select_related(
            "board__manufacturer", "component", "project"
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

        unit_count = _inventory_unit_count(payload.get("quantity", 1))
        requested_inventory_id = str(payload.get("inventory_id") or "").strip()
        requested_serial = str(payload.get("serial_number") or "").strip()
        if unit_count > 1 and requested_inventory_id:
            raise ValidationError({
                "inventory_id": "Leave Inventory ID blank when adding multiple items so each unit can receive its own ID."
            })
        if unit_count > 1 and requested_serial:
            raise ValidationError({
                "serial_number": "Add items one at a time when assigning a serial or unique ID."
            })

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
            project = Project.objects.filter(owner=request.user).filter(pk=payload["project_id"]).first()
            if not project:
                return _error("Selected project was not found.")

        created_items = []
        with transaction.atomic():
            for index in range(unit_count):
                item = InventoryItem(
                    owner=request.user,
                    inventory_id=(requested_inventory_id if unit_count == 1 else _next_inventory_id(request.user, item_type)),
                    item_type=item_type,
                    board=board,
                    component=component,
                    custom_name=str(payload.get("custom_name") or "").strip(),
                    quantity=Decimal("1"),
                    status=str(payload.get("status") or "available"),
                    project=project,
                    location=str(payload.get("location") or "").strip(),
                    serial_number=(requested_serial if unit_count == 1 else ""),
                    purchase_price=_parse_decimal(payload.get("purchase_price"), "purchase_price"),
                    currency=str(payload.get("currency") or settings.MAKERVAULT_CURRENCY).upper()[:3],
                    supplier=str(payload.get("supplier") or "").strip(),
                    purchase_url=str(payload.get("purchase_url") or "").strip(),
                    notes=str(payload.get("notes") or "").strip(),
                )
                if not item.inventory_id:
                    item.inventory_id = _next_inventory_id(request.user, item_type)
                item.full_clean()
                item.save()
                _record_inventory_history(item, request.user, created=True)
                created_items.append(item)

        serialised = [_serialise_inventory(item) for item in created_items]
        return JsonResponse({
            "item": serialised[0],
            "items": serialised,
            "created_count": len(serialised),
        }, status=201)
    except ValidationError as exc:
        return _validation_response(exc)
    except (ValueError, IntegrityError) as exc:
        return _error(str(exc))


@login_required
@require_http_methods(["GET", "PATCH", "DELETE"])
def inventory_detail(request, item_id):
    base_qs = InventoryItem.objects.filter(owner=request.user).select_related(
        "board__manufacturer", "board__source", "component",
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
                "bom_item__component",
            ).order_by("bom_item__project__name", "bom_item__created_at")
        ]
        return JsonResponse({"item": payload})

    if request.method == "DELETE":
        denied = _require_permission(request, "core.delete_inventoryitem")
        if denied:
            return denied
        with transaction.atomic():
            item = InventoryItem.objects.filter(owner=request.user).select_for_update().filter(pk=item_id).first()
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
            item = InventoryItem.objects.filter(owner=request.user).select_for_update().filter(pk=item_id).first()
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
                requested_quantity = _inventory_unit_count(payload["quantity"])
                if requested_quantity != 1:
                    raise ValidationError({
                        "quantity": "Each inventory record represents one physical item. Add another inventory record instead of increasing quantity."
                    })
                allocated = item.bom_allocations.aggregate(total=Sum("quantity"))["total"] or Decimal("0")
                if allocated > Decimal("1"):
                    raise ValidationError({
                        "quantity": f"This legacy grouped record still has {allocated} allocated. Split it into individual inventory units before changing quantity."
                    })
                item.quantity = Decimal("1")
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
                    project = Project.objects.filter(owner=request.user).filter(pk=payload["project_id"]).first()
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
            item = InventoryItem.objects.filter(owner=request.user).select_related(
                "board__manufacturer", "project"
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
        qs = ComponentModel.objects.select_related("category", "source")
        query = request.GET.get("q", "").strip()
        if query:
            qs = qs.filter(
                Q(name__icontains=query)
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
    component = ComponentModel.objects.select_related("category", "source").filter(pk=component_id).first()
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
    component = ComponentModel.objects.select_related("category", "source").filter(pk=component_id).first()
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
        qs = FileAsset.objects.filter(owner=request.user).exclude(category="image").filter(superseded_by__isnull=True).select_related(
            "project", "board__manufacturer", "component__category"
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
        project = Project.objects.filter(owner=request.user).filter(pk=project_id).first()
        if not project:
            return _error("Selected project was not found.")
        project_denied = _require_permission(request, "core.change_project")
        if project_denied:
            return project_denied

    original_name = Path(uploaded.name or "file").name
    try:
        ensure_storage_capacity(request.user, getattr(uploaded, "size", 0) or 0)
    except StorageQuotaExceeded as exc:
        return _storage_quota_response(request, exc)
    try:
        checksum = _sha256_upload(uploaded)
        asset = FileAsset(
            owner=request.user,
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
    asset = FileAsset.objects.filter(owner=request.user).select_related("project").filter(pk=asset_id).exclude(category="image").first()
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
                new_project = Project.objects.filter(owner=request.user).filter(pk=project_id).first()
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
def file_versions(request, asset_id):
    asset = FileAsset.objects.filter(owner=request.user).select_related(
        "project", "board", "component", "supersedes"
    ).filter(pk=asset_id).exclude(category="image").first()
    if not asset:
        return _error("File not found.", status=404)

    if request.method == "GET":
        versions = []
        current = asset
        seen = set()
        while current and current.pk not in seen:
            seen.add(current.pk)
            versions.append(_serialise_file_asset(current))
            current = current.supersedes
        return JsonResponse({"versions": versions})

    denied = _require_permission(request, "core.change_fileasset")
    if denied:
        return denied
    if asset.project:
        project_denied = _require_permission(request, "core.change_project")
        if project_denied:
            return project_denied
    if FileAsset.objects.filter(owner=request.user).filter(supersedes=asset).exists():
        return _error(
            "A newer version already exists. Refresh MakerVault and upload from the latest version.",
            status=409,
        )

    uploaded = request.FILES.get("file")
    if not uploaded:
        return _error("Choose a file to upload.")
    version = str(request.POST.get("version") or "").strip()[:80]
    if not version:
        return _error("Enter a version label for the new file.")

    original_name = Path(uploaded.name or "file").name
    try:
        ensure_storage_capacity(request.user, getattr(uploaded, "size", 0) or 0)
    except StorageQuotaExceeded as exc:
        return _storage_quota_response(request, exc)
    stored_asset = None
    try:
        checksum = _sha256_upload(uploaded)
        metadata = dict(asset.metadata or {})
        metadata.update({
            "original_name": original_name,
            "size_bytes": getattr(uploaded, "size", 0) or 0,
            "extension": Path(original_name).suffix.lower(),
            "uploaded_from": "file_new_version",
            "supersedes_id": str(asset.id),
        })
        stored_asset = FileAsset(
            owner=asset.owner or request.user,
            project=asset.project,
            board=asset.board,
            component=asset.component,
            category=asset.category,
            name=asset.name,
            version=version,
            description=str(request.POST.get("description") or asset.description or "").strip(),
            sha256=checksum,
            metadata=metadata,
            supersedes=asset,
        )
        stored_asset.file = uploaded
        stored_asset.full_clean()
        stored_asset.save()
        if asset.project:
            asset.project.save(update_fields=["updated_at"])
        return JsonResponse({"file": _serialise_file_asset(stored_asset)}, status=201)
    except ValidationError as exc:
        if stored_asset and stored_asset.file:
            try:
                stored_asset.file.delete(save=False)
            except OSError:
                pass
        return _validation_response(exc)


@login_required
@require_http_methods(["GET", "POST"])
def projects_lookup(request):
    if request.method == "GET":
        qs = Project.objects.filter(owner=request.user).select_related("created_by").prefetch_related(
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
            owner=request.user,
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
        project = Project.objects.filter(owner=request.user).select_related("created_by").prefetch_related("inventory_items", "files", "repositories").get(pk=project.pk)
        return JsonResponse({"project": _serialise_project(project, detailed=True)}, status=201)
    except ValidationError as exc:
        return _validation_response(exc)


@login_required
@require_http_methods(["GET", "PATCH", "DELETE"])
def project_detail(request, project_id):
    project = Project.objects.filter(owner=request.user).select_related("created_by").prefetch_related(
        "inventory_items__board__manufacturer",
        "inventory_items__component",
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
        project = Project.objects.filter(owner=request.user).select_related("created_by").prefetch_related(
            "inventory_items__board__manufacturer",
            "inventory_items__component",
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
    if not excluding_id and inventory.status != "available":
        raise ValidationError({
            "inventory_item": f"{inventory.inventory_id} is {inventory.get_status_display().lower()} and is not free for allocation."
        })
    if not excluding_id and inventory.project_id and inventory.project_id != bom_item.project_id:
        raise ValidationError({
            "inventory_item": f"{inventory.inventory_id} is already assigned to another project."
        })

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
    project = Project.objects.filter(owner=request.user).filter(pk=project_id).first()
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
        item = BOMItem.objects.select_related("board__manufacturer", "component__category").get(pk=item.pk)
        return JsonResponse({"bom_item": _serialise_bom_item(item)}, status=201)
    except ValidationError as exc:
        return _validation_response(exc)
    except ValueError as exc:
        return _error(str(exc))


@login_required
@require_http_methods(["PATCH", "DELETE"])
def project_bom_item_detail(request, project_id, bom_id):
    project = Project.objects.filter(owner=request.user).filter(pk=project_id).first()
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
    project = Project.objects.filter(owner=request.user).filter(pk=project_id).first()
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
                    owner=project.owner or request.user,
                    inventory_id=(
                        str(create_payload.get("inventory_id") or "").strip()
                        or _next_inventory_id(request.user, item_type)
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
                inventory = InventoryItem.objects.filter(owner=request.user).select_for_update().filter(pk=inventory_id).first()
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

            inventory = InventoryItem.objects.filter(owner=request.user).select_related(
                "board__manufacturer", "project"
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
    project = Project.objects.filter(owner=request.user).filter(pk=project_id).first()
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

            inventory = InventoryItem.objects.filter(owner=request.user).select_for_update().get(pk=allocation.inventory_item_id)
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
    project = Project.objects.filter(owner=request.user).select_related("created_by").prefetch_related("inventory_items", "files", "repositories").filter(pk=project_id).first()
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
        existing_size = 0
        if project.cover_image:
            try:
                existing_size = max(int(project.cover_image.size or 0), 0)
            except (FileNotFoundError, OSError, ValueError, TypeError):
                existing_size = 0
        try:
            ensure_storage_capacity(request.user, getattr(content, "size", 0) or 0, replacing_bytes=existing_size)
        except StorageQuotaExceeded as exc:
            return _storage_quota_response(request, exc)
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
    project = Project.objects.filter(owner=request.user).filter(pk=project_id).first()
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
        try:
            ensure_storage_capacity(request.user, getattr(content, "size", 0) or 0)
        except StorageQuotaExceeded as exc:
            return _storage_quota_response(request, exc)
        asset = FileAsset(
            owner=project.owner or request.user,
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
    project = Project.objects.filter(owner=request.user).filter(pk=project_id).first()
    if not project:
        return _error("Project not found.", status=404)
    denied = _require_permission(request, "core.change_project")
    if denied:
        return denied
    asset = FileAsset.objects.filter(owner=request.user).filter(pk=asset_id, project=project, category="image").first()
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
    project = Project.objects.filter(owner=request.user).filter(pk=project_id).first()
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
        ensure_storage_capacity(request.user, getattr(uploaded, "size", 0) or 0)
    except StorageQuotaExceeded as exc:
        return _storage_quota_response(request, exc)
    try:
        checksum = _sha256_upload(uploaded)
        asset = FileAsset(
            owner=project.owner or request.user,
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
    project = Project.objects.filter(owner=request.user).filter(pk=project_id).first()
    if not project:
        return _error("Project not found.", status=404)
    denied = _require_permission(request, "core.change_project")
    if denied:
        return denied
    asset = FileAsset.objects.filter(owner=request.user).filter(pk=asset_id, project=project).exclude(category="image").first()
    if not asset:
        return _error("Project file not found.", status=404)

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
    project = Project.objects.filter(owner=request.user).filter(pk=project_id).first()
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
    project = Project.objects.filter(owner=request.user).filter(pk=project_id).first()
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


def _attribution_row(kind, obj, variant="base"):
    if variant == "multi_material":
        metadata = getattr(obj, "image_multi_material_metadata", {}) or {}
        image = getattr(obj, "image_multi_material", None)
    else:
        metadata = getattr(obj, "specifications", None)
        if metadata is None:
            metadata = getattr(obj, "image_metadata", {})
        metadata = metadata or {}
        image = getattr(obj, "image", None)
    provider = metadata.get("image_source_provider") or ""
    page = metadata.get("image_source_page") or ""
    image_url = metadata.get("image_source_url") or metadata.get("external_image_url") or ""
    if not (provider or page or image_url):
        return None
    return {
        "kind": kind,
        "id": str(obj.id),
        "name": str(obj),
        "provider": provider or "External source",
        "author": metadata.get("image_author") or "",
        "license": metadata.get("image_license") or "",
        "source_page": page or image_url,
        "cached": bool(image),
    }


@login_required
@require_http_methods(["GET"])
def attributions(request):
    rows = []
    for board in BoardModel.objects.select_related("manufacturer").exclude(specifications={}):
        row = _attribution_row("Board", board)
        if row:
            rows.append(row)
    for component in ComponentModel.objects.select_related("category").exclude(specifications={}):
        row = _attribution_row("Component", component)
        if row:
            rows.append(row)
    for printer_model in PrinterCatalogModel.objects.select_related("manufacturer"):
        row = _attribution_row("3D printer", printer_model)
        if row:
            rows.append(row)
        combo_row = _attribution_row("3D printer + multi-material", printer_model, variant="multi_material")
        if combo_row:
            combo_row["name"] = (
                f"{printer_model} + {printer_model.get_multi_material_system_display()}"
                if printer_model.multi_material_system
                else f"{printer_model} + multi-material"
            )
            rows.append(combo_row)
    rows.sort(key=lambda row: (row["provider"].lower(), row["name"].lower()))
    return JsonResponse({
        "rows": rows,
        "summary": {
            "total": len(rows),
            "with_license": sum(1 for row in rows if row["license"]),
            "needs_review": sum(1 for row in rows if not row["license"]),
        },
    })


PRINTING_INTEGRATION_DEFAULTS = {
    "spoolman": {"status": "not_configured", "sync_direction": "bidirectional"},
    "simplyprint": {"status": "not_configured", "sync_direction": "import", "endpoint_url": "https://api.simplyprint.io"},
    "creality_cfs": {"status": "ready", "sync_direction": "import"},
    "bambu_ams": {"status": "planned", "sync_direction": "import"},
    "elegoo": {"status": "planned", "sync_direction": "import"},
    "qidi": {"status": "planned", "sync_direction": "import"},
    "snapmaker": {"status": "planned", "sync_direction": "import"},
}


def _ensure_printing_integrations(owner):
    rows = []
    for provider, defaults in PRINTING_INTEGRATION_DEFAULTS.items():
        row, created = PrintingIntegrationSetting.objects.get_or_create(
            owner=owner,
            provider=provider,
            defaults=defaults,
        )
        if provider == "simplyprint":
            changed = []
            if not row.endpoint_url:
                row.endpoint_url = "https://api.simplyprint.io"
                changed.append("endpoint_url")
            if row.status == "planned":
                row.status = "not_configured"
                changed.append("status")
            if row.sync_direction != "import":
                row.sync_direction = "import"
                changed.append("sync_direction")
            if changed:
                row.save(update_fields=[*changed, "updated_at"])
        rows.append(row)
    return rows


def _serialise_printing_integration(item):
    extra = {}
    safe_config = {
        key: value
        for key, value in (item.config or {}).items()
        if key not in {"pending_reviews", "api_key"}
    }
    if item.provider == "simplyprint":
        safe_config["api_key_configured"] = bool((item.config or {}).get("api_key"))
    if item.provider == "creality_cfs":
        compatible = Printer.objects.filter(
            owner=item.owner,
            is_active=True,
            catalog_model__multi_material_system="creality_cfs",
        )
        installed = compatible.filter(multi_material_installed=True)
        configured = installed.exclude(connection_host="")
        extra = {
            "compatible_printers": compatible.count(),
            "installed_printers": installed.count(),
            "configured_printers": configured.count(),
        }
    elif item.provider == "spoolman":
        pending_reviews = (item.config or {}).get("pending_reviews") or []
        ignored_ids = (item.config or {}).get("ignored_external_ids") or []
        extra = {
            "linked_spools": ExternalSpoolLink.objects.filter(provider="spoolman", spool__owner=item.owner).count(),
            "pending_review_count": len(pending_reviews) if isinstance(pending_reviews, list) else 0,
            "ignored_import_count": len(ignored_ids) if isinstance(ignored_ids, list) else 0,
            "authority_policy": "makervault_primary",
        }
    elif item.provider == "simplyprint":
        extra = {
            "linked_printers": ExternalPrinterLink.objects.filter(provider="simplyprint", printer__owner=item.owner).count(),
            "linked_spools": ExternalSpoolLink.objects.filter(provider="simplyprint", spool__owner=item.owner).count(),
            "imported_print_jobs": PrintJob.objects.filter(
                owner=item.owner,
                settings__external_provider="simplyprint"
            ).count(),
            "authority_policy": "makervault_primary",
            "read_only": True,
        }
    return {
        "provider": item.provider,
        "name": item.get_provider_display(),
        "enabled": item.enabled,
        "endpoint_url": item.endpoint_url,
        "sync_direction": item.sync_direction,
        "sync_direction_label": item.get_sync_direction_display(),
        "status": item.status,
        "status_label": item.get_status_display(),
        "auto_sync": item.auto_sync,
        "sync_interval_minutes": item.sync_interval_minutes,
        "last_checked_at": item.last_checked_at.isoformat() if item.last_checked_at else None,
        "last_sync_at": item.last_sync_at.isoformat() if item.last_sync_at else None,
        "next_sync_at": item.next_sync_at.isoformat() if item.next_sync_at else None,
        "last_sync_triggered_by": item.last_sync_triggered_by,
        "last_sync_result": item.last_sync_result or {},
        "last_error": item.last_error,
        "can_sync": item.provider in {"spoolman", "simplyprint", "creality_cfs"},
        "config": safe_config,
        **extra,
    }


def _serialise_printing_integration_status(item):
    return {
        "provider": item.provider,
        "name": item.get_provider_display(),
        "status": item.status,
        "status_label": item.get_status_display(),
        "last_sync_at": item.last_sync_at.isoformat() if item.last_sync_at else None,
        "next_sync_at": item.next_sync_at.isoformat() if item.next_sync_at else None,
        "auto_sync": item.auto_sync,
        "last_error": item.last_error,
    }


@login_required
@require_http_methods(["GET"])
def printing_integration_settings(request):
    if not request.user.is_staff:
        return _error("Administrator access is required.", status=403)
    rows = _ensure_printing_integrations(request.user)
    return JsonResponse({
        "rows": [_serialise_printing_integration(item) for item in rows],
    })


@login_required
@require_http_methods(["PATCH"])
def printing_integration_detail(request, provider):
    if not request.user.is_staff:
        return _error("Administrator access is required.", status=403)
    if provider not in dict(PrintingIntegrationSetting.PROVIDERS):
        return _error("Unknown printing integration.", status=404)
    item, _ = PrintingIntegrationSetting.objects.get_or_create(
        owner=request.user,
        provider=provider,
        defaults=PRINTING_INTEGRATION_DEFAULTS.get(provider, {}),
    )
    try:
        payload = _read_json(request)
        if "enabled" in payload:
            item.enabled = bool(payload.get("enabled"))
        if "endpoint_url" in payload:
            item.endpoint_url = str(payload.get("endpoint_url") or "").strip()
        if "sync_direction" in payload:
            direction = str(payload.get("sync_direction") or "import")
            if direction not in dict(PrintingIntegrationSetting.SYNC_DIRECTIONS):
                return _error("Unknown sync direction.")
            item.sync_direction = direction
        if "auto_sync" in payload:
            item.auto_sync = bool(payload.get("auto_sync"))
        if "sync_interval_minutes" in payload:
            try:
                item.sync_interval_minutes = int(payload.get("sync_interval_minutes"))
            except (TypeError, ValueError) as exc:
                raise ValidationError({
                    "sync_interval_minutes": "Enter a whole number of minutes."
                }) from exc

        if item.provider == "simplyprint":
            config = dict(item.config or {})
            if "company_id" in payload:
                config["company_id"] = str(payload.get("company_id") or "").strip()
            if "api_key" in payload and str(payload.get("api_key") or "").strip():
                config["api_key"] = str(payload.get("api_key") or "").strip()
            if payload.get("clear_api_key") is True:
                config.pop("api_key", None)
            if "history_page_size" in payload:
                try:
                    history_page_size = int(payload.get("history_page_size"))
                except (TypeError, ValueError) as exc:
                    raise ValidationError({
                        "history_page_size": "Enter a whole number between 1 and 100."
                    }) from exc
                if history_page_size < 1 or history_page_size > 100:
                    raise ValidationError({
                        "history_page_size": "Enter a whole number between 1 and 100."
                    })
                config["history_page_size"] = history_page_size
            item.config = config
            item.endpoint_url = item.endpoint_url or "https://api.simplyprint.io"
            item.sync_direction = "import"

        if payload.get("reset_ignored_imports") is True:
            config = dict(item.config or {})
            config["ignored_external_ids"] = []
            item.config = config

        if not item.enabled:
            item.status = "disabled"
            item.last_error = ""
            item.next_sync_at = None
        elif item.provider == "spoolman" and not item.endpoint_url:
            item.status = "not_configured"
            item.next_sync_at = None
        elif item.provider == "creality_cfs":
            configured = Printer.objects.filter(owner=request.user).filter(
                is_active=True,
                multi_material_installed=True,
                catalog_model__multi_material_system="creality_cfs",
            ).exclude(connection_host="").exists()
            if not configured:
                item.status = "not_configured"
                item.next_sync_at = None
            elif item.status in {"disabled", "not_configured", "ready"}:
                item.status = "disconnected"
        elif item.provider == "simplyprint":
            config = item.config or {}
            if not str(config.get("company_id") or "").strip() or not str(config.get("api_key") or "").strip():
                item.status = "not_configured"
                item.next_sync_at = None
            elif item.status in {"disabled", "not_configured", "ready", "planned"}:
                item.status = "disconnected"
        elif item.provider in {"bambu_ams", "elegoo", "qidi", "snapmaker"}:
            item.status = "planned"
            item.auto_sync = False
            item.next_sync_at = None
        elif item.status in {"disabled", "not_configured", "ready"}:
            item.status = "disconnected"

        if item.enabled and item.auto_sync and item.provider in {"spoolman", "simplyprint", "creality_cfs"}:
            item.next_sync_at = timezone.now() + timedelta(minutes=item.sync_interval_minutes)
        elif not item.auto_sync:
            item.next_sync_at = None

        item.full_clean()
        item.save()
        return JsonResponse({"item": _serialise_printing_integration(item)})
    except ValidationError as exc:
        return _validation_response(exc)


@login_required
@require_http_methods(["POST"])
def printing_integration_test(request, provider):
    if not request.user.is_staff:
        return _error("Administrator access is required.", status=403)
    if provider not in dict(PrintingIntegrationSetting.PROVIDERS):
        return _error("Unknown printing integration.", status=404)
    item, _ = PrintingIntegrationSetting.objects.get_or_create(
        owner=request.user,
        provider=provider,
        defaults=PRINTING_INTEGRATION_DEFAULTS.get(provider, {}),
    )

    try:
        if provider == "spoolman":
            result = probe_spoolman(item.endpoint_url)
            item.endpoint_url = result["endpoint_url"]
            item.status = "connected"
            item.last_error = ""
            item.last_checked_at = timezone.now()
            item.config = {
                **(item.config or {}),
                "server_info": result.get("info") or {},
            }
            item.save()
        elif provider == "simplyprint":
            config = dict(item.config or {})
            result = probe_simplyprint(
                item.endpoint_url or "https://api.simplyprint.io",
                config.get("company_id"),
                config.get("api_key"),
            )
            item.endpoint_url = result["endpoint_url"]
            item.status = "connected"
            item.last_error = ""
            item.last_checked_at = timezone.now()
            config["last_probe_message"] = result.get("message") or ""
            item.config = config
            item.save()
        elif provider == "creality_cfs":
            item, _ = sync_printing_integration(
                provider,
                triggered_by=f"test:user:{request.user.get_username()}",
                owner=request.user,
            )
        else:
            item.last_checked_at = timezone.now()
            item.status = "planned"
            item.last_error = ""
            item.save()
        return JsonResponse({"item": _serialise_printing_integration(item)})
    except (PrintingIntegrationError, PrintingSyncError) as exc:
        item.refresh_from_db()
        if item.status not in {"disconnected", "error"}:
            item.status = "disconnected"
            item.last_error = str(exc)
            item.last_checked_at = timezone.now()
            item.save(update_fields=["status", "last_error", "last_checked_at", "updated_at"])
        return JsonResponse(
            {"error": str(exc), "item": _serialise_printing_integration(item)},
            status=502,
        )


@login_required
@require_http_methods(["GET"])
def printing_integration_reviews(request, provider):
    if not request.user.is_staff:
        return _error("Administrator access is required.", status=403)
    item = PrintingIntegrationSetting.objects.filter(owner=request.user).filter(provider=provider).first()
    if not item:
        return _error("Integration is not configured.", status=404)
    if provider != "spoolman":
        return JsonResponse({"rows": [], "provider": provider})
    rows = (item.config or {}).get("pending_reviews") or []
    if not isinstance(rows, list):
        rows = []
    return JsonResponse({"rows": rows, "provider": provider})


@login_required
@require_http_methods(["POST"])
def printing_integration_review_resolve(request, provider, external_id):
    if not request.user.is_staff:
        return _error("Administrator access is required.", status=403)
    item = PrintingIntegrationSetting.objects.filter(owner=request.user).filter(provider=provider).first()
    if not item:
        return _error("Integration is not configured.", status=404)
    try:
        payload = _read_json(request)
        if provider != "spoolman":
            return _error("Review resolution is not implemented for this integration yet.", status=409)
        result = resolve_spoolman_review(
            item,
            external_id,
            str(payload.get("action") or "").strip(),
            spool_id=payload.get("spool_id"),
            filament_id=payload.get("filament_id"),
        )
        item.refresh_from_db()
        return JsonResponse({
            "item": _serialise_printing_integration(item),
            "result": result,
        })
    except PrintingSyncError as exc:
        return _error(str(exc), status=409)


@login_required
@require_http_methods(["POST"])
def printing_integration_sync_now(request, provider):
    if not request.user.is_staff:
        return _error("Administrator access is required.", status=403)
    if provider not in {"spoolman", "simplyprint", "creality_cfs"}:
        return _error("This integration does not have a sync adapter yet.", status=409)
    try:
        item, result = sync_printing_integration(
            provider,
            triggered_by=f"user:{request.user.get_username()}",
            owner=request.user,
        )
        return JsonResponse({
            "item": _serialise_printing_integration(item),
            "result": result,
        })
    except PrintingSyncError as exc:
        item = PrintingIntegrationSetting.objects.filter(owner=request.user).filter(provider=provider).first()
        payload = {"error": str(exc)}
        if item:
            payload["item"] = _serialise_printing_integration(item)
        return JsonResponse(payload, status=502)



def _serialise_catalogue_maintenance(config):
    return {
        "enabled": config.enabled,
        "interval_hours": config.interval_hours,
        "check_board_data": config.check_board_data,
        "check_printer_data": config.check_printer_data,
        "check_images": config.check_images,
        "last_run_at": config.last_run_at.isoformat() if config.last_run_at else "",
        "next_run_at": config.next_run_at.isoformat() if config.next_run_at else "",
        "last_triggered_by": config.last_triggered_by,
        "server_board_enrichment_enabled": bool(settings.ENRICH_BOARD_CATALOGUE),
        "server_printer_catalogue_enabled": bool(settings.SYNC_ORCASLICER_PRINTER_CATALOGUE),
        "server_printer_catalogue_ref": settings.ORCASLICER_PRINTER_CATALOGUE_REF,
        "printer_catalogue_models": PrinterCatalogModel.objects.count(),
        "printer_catalogue_manufacturers": PrinterManufacturer.objects.count(),
        "server_image_seeding_enabled": bool(settings.SEED_CATALOGUE_IMAGES),
    }


@login_required
@require_http_methods(["GET"])
def catalogue_coverage(request):
    if not request.user.is_staff:
        return _error("Administrator access is required.", status=403)
    return JsonResponse(catalogue_coverage_summary())


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
        if "check_printer_data" in payload:
            config.check_printer_data = bool(payload["check_printer_data"])
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


def _analyse_revision_link(revision, link):
    metadata = dict(revision.geometry_metadata or {})
    try:
        analysis = analyse_file_asset(link.file_asset)
        analysis["analysed_at"] = timezone.now().isoformat()
        analysis["source_link_id"] = str(link.id)
        metadata["analysis"] = analysis
        metadata["analysis_status"] = "ready"
        metadata["analysis_error"] = ""
    except ModelAnalysisError as exc:
        metadata["analysis_status"] = "error"
        metadata["analysis_error"] = str(exc)
    revision.geometry_metadata = metadata
    revision.save(update_fields=["geometry_metadata", "updated_at"])
    return metadata


def _select_revision_analysis_link(revision, asset_id=None):
    links = list(revision.assets.select_related("file_asset").all())
    if asset_id:
        return next((link for link in links if str(link.file_asset_id) == str(asset_id)), None)
    supported = []
    for link in links:
        asset = link.file_asset
        original_name = str((asset.metadata or {}).get("original_name") or "")
        filename = original_name or (Path(asset.file.name).name if asset.file else "") or asset.name
        if Path(filename).suffix.lower() not in {".stl", ".3mf"}:
            continue
        score = (
            int(link.is_primary) * 10
            + int(link.role == "model") * 4
            + int(link.role == "slicer") * 2
        )
        supported.append((score, link))
    supported.sort(key=lambda item: item[0], reverse=True)
    return supported[0][1] if supported else None


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
            "filename": str((asset.metadata or {}).get("original_name") or asset.name or ""),
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
            "geometry_metadata": revision.geometry_metadata or {},
            "geometry_analysis": (revision.geometry_metadata or {}).get("analysis"),
            "analysis_status": (revision.geometry_metadata or {}).get("analysis_status", ""),
            "analysis_error": (revision.geometry_metadata or {}).get("analysis_error", ""),
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


def _printer_official_image(item, *, multi_material=False):
    features = item.features or {}
    prefix = "official_image_multi_material" if multi_material else "official_image"
    url = str(features.get(f"{prefix}_url") or "").strip()
    if not url.startswith("https://"):
        return {"url": "", "source_page": "", "source_provider": ""}
    return {
        "url": url,
        "source_page": str(features.get(f"{prefix}_source_page") or item.source_url or "").strip(),
        "source_provider": str(features.get(f"{prefix}_source_provider") or f"{item.manufacturer.name} official").strip(),
    }


def _serialise_printer_catalog_model(item):
    official = _printer_official_image(item)
    official_multi = _printer_official_image(item, multi_material=True)
    cached_image = _image_url(item)
    cached_multi = _image_url(
        item,
        "image_multi_material",
        "image_multi_material_metadata",
    )
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
        "image": cached_image or official["url"],
        "image_cached": bool(item.image),
        "image_remote_official": bool(not cached_image and official["url"]),
        "image_source_page": (item.image_metadata or {}).get("image_source_page") or official["source_page"],
        "image_source_provider": (item.image_metadata or {}).get("image_source_provider") or official["source_provider"],
        "image_license": (item.image_metadata or {}).get("image_license") or "",
        "image_author": (item.image_metadata or {}).get("image_author") or "",
        "image_multi_material": cached_multi or official_multi["url"],
        "image_multi_material_cached": bool(item.image_multi_material),
        "image_multi_material_remote_official": bool(not cached_multi and official_multi["url"]),
        "image_multi_material_source_page": (item.image_multi_material_metadata or {}).get("image_source_page") or official_multi["source_page"],
        "image_multi_material_source_provider": (item.image_multi_material_metadata or {}).get("image_source_provider") or official_multi["source_provider"],
        "image_multi_material_license": (item.image_multi_material_metadata or {}).get("image_license") or "",
        "image_multi_material_author": (item.image_multi_material_metadata or {}).get("image_author") or "",
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


def _spool_cost_per_g(spool):
    if spool.purchase_cost is None or not spool.initial_weight_g:
        return None
    if spool.initial_weight_g <= 0:
        return None
    return spool.purchase_cost / spool.initial_weight_g


def _estimated_spool_material_cost(spool, used_g, waste_g):
    unit_cost = _spool_cost_per_g(spool) if spool else None
    if unit_cost is None:
        return None
    total_g = (used_g or Decimal("0")) + (waste_g or Decimal("0"))
    return (unit_cost * total_g).quantize(Decimal("0.01"))


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
        "rfid_uid": spool.rfid_uid,
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
        "purchase_cost": _float(spool.purchase_cost),
        "currency": spool.currency,
        "cost_per_g": _float(_spool_cost_per_g(spool)),
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
        "remaining_percent": (slot.metadata or {}).get("remaining_percent"),
        "vendor": (slot.metadata or {}).get("vendor", ""),
        "product_name": (slot.metadata or {}).get("product_name", ""),
        "rfid_detected": bool((slot.metadata or {}).get("rfid_detected")),
        "material_code": (slot.metadata or {}).get("material_code", ""),
        "physical_tag_uid_available": bool((slot.metadata or {}).get("physical_tag_uid_available")),
        "selected": bool((slot.metadata or {}).get("selected")),
        "rfid_uid": slot.rfid_uid,
        "external_ref": slot.external_ref,
        "is_loaded": slot.is_loaded,
        "last_seen_at": slot.last_seen_at.isoformat() if slot.last_seen_at else None,
    }


def _serialise_printer_connection(connection):
    definition = PRINTER_ADAPTERS.get(connection.adapter)
    stale_after_seconds = max(60, int(connection.poll_interval_seconds or 30) * 3)
    stale = bool(
        connection.enabled
        and connection.status == "connected"
        and connection.last_seen_at
        and connection.last_seen_at < timezone.now() - timedelta(seconds=stale_after_seconds)
    )
    safe_config = {
        key: value
        for key, value in (connection.config or {}).items()
        if key not in {"api_key", "token", "password", "access_code"}
    }
    safe_config["api_key_configured"] = bool(str((connection.config or {}).get("api_key") or "").strip())
    return {
        "id": str(connection.id),
        "printer_id": str(connection.printer_id),
        "adapter": connection.adapter,
        "adapter_label": definition.label if definition else connection.get_adapter_display(),
        "enabled": connection.enabled,
        "endpoint_url": connection.endpoint_url,
        "poll_interval_seconds": connection.poll_interval_seconds,
        "status": connection.status,
        "status_label": "Stale" if stale else connection.get_status_display(),
        "stale": stale,
        "stale_after_seconds": stale_after_seconds,
        "supported": bool(definition and definition.supported),
        "experimental": bool(definition and definition.experimental),
        "local_first": bool(definition and definition.local_first),
        "capabilities": connection.capabilities or (dict(definition.capabilities) if definition else {}),
        "snapshot": connection.last_snapshot or {},
        "last_checked_at": connection.last_checked_at.isoformat() if connection.last_checked_at else None,
        "last_seen_at": connection.last_seen_at.isoformat() if connection.last_seen_at else None,
        "last_error": connection.last_error,
        "config": safe_config,
    }


def _serialise_printer(printer):
    maker = printer.printer_manufacturer or printer.manufacturer
    catalogue = printer.catalog_model
    live_connections = [
        _serialise_printer_connection(connection)
        for connection in printer.live_connections.all()
    ]
    live_status = next(
        (
            connection
            for connection in live_connections
            if connection["enabled"]
            and connection["status"] == "connected"
            and not connection["stale"]
        ),
        None,
    )
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
        "multi_material_installed": printer.multi_material_installed,
        "installed_multi_material_system": (
            catalogue.multi_material_system
            if catalogue and printer.multi_material_installed
            else ""
        ),
        "installed_multi_material_label": (
            catalogue.get_multi_material_system_display()
            if catalogue and printer.multi_material_installed and catalogue.multi_material_system
            else ""
        ),
        "connection_host": printer.connection_host,
        "build_volume": {
            "x": _float(printer.build_volume_x_mm),
            "y": _float(printer.build_volume_y_mm),
            "z": _float(printer.build_volume_z_mm),
        },
        "nozzle_mm": _float(printer.nozzle_mm),
        "catalogue": _serialise_printer_catalog_model(catalogue) if catalogue else None,
        "slots": [_serialise_printer_slot(slot) for slot in printer.filament_slots.all()],
        "external_links": [
            {
                "provider": link.provider,
                "provider_label": link.get_provider_display(),
                "external_id": link.external_id,
                "external_url": link.external_url,
                "last_synced_at": link.last_synced_at.isoformat() if link.last_synced_at else None,
            }
            for link in printer.external_links.all()
        ],
        "simplyprint": (printer.profile_data or {}).get("simplyprint") or {},
        "live_connections": live_connections,
        "live_status": live_status,
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


def _printing_analytics(owner):
    status_rows = {
        row["status"]: row["count"]
        for row in PrintJob.objects.filter(owner=owner).values("status").annotate(count=Count("id"))
    }
    successful = int(status_rows.get("success", 0))
    failed = int(status_rows.get("failed", 0))
    completed = successful + failed
    total_jobs = sum(int(value) for value in status_rows.values())

    job_totals = PrintJob.objects.filter(owner=owner).aggregate(
        actual_minutes=Sum("actual_minutes"),
        estimated_minutes=Sum("estimated_minutes"),
    )
    usage_totals = PrintMaterialUsage.objects.filter(print_job__owner=owner).aggregate(
        used_g=Sum("used_g"),
        waste_g=Sum("waste_g"),
    )
    default_currency = settings.MAKERVAULT_CURRENCY
    material_cost = (
        PrintMaterialUsage.objects.filter(print_job__owner=owner, currency=default_currency)
        .aggregate(total=Sum("material_cost"))
        .get("total")
    )
    foreign_cost_rows = PrintMaterialUsage.objects.filter(print_job__owner=owner).exclude(
        currency=default_currency
    ).exclude(material_cost=None).count()

    printer_rows = []
    for row in (
        PrintJob.objects.filter(owner=owner).values("printer_id", "printer__name")
        .annotate(
            jobs=Count("id"),
            successes=Count("id", filter=Q(status="success")),
            failures=Count("id", filter=Q(status="failed")),
            actual_minutes=Sum("actual_minutes"),
        )
        .order_by("-jobs", "printer__name")
    ):
        printer_completed = int(row["successes"] or 0) + int(row["failures"] or 0)
        printer_rows.append({
            "printer_id": str(row["printer_id"]),
            "printer": row["printer__name"],
            "jobs": int(row["jobs"] or 0),
            "successes": int(row["successes"] or 0),
            "failures": int(row["failures"] or 0),
            "success_rate": (
                round((int(row["successes"] or 0) / printer_completed) * 100, 1)
                if printer_completed
                else None
            ),
            "actual_minutes": int(row["actual_minutes"] or 0),
        })

    return {
        "jobs": total_jobs,
        "successful": successful,
        "failed": failed,
        "completed": completed,
        "success_rate": round((successful / completed) * 100, 1) if completed else None,
        "actual_minutes": int(job_totals["actual_minutes"] or 0),
        "estimated_minutes": int(job_totals["estimated_minutes"] or 0),
        "filament_used_g": _float(usage_totals["used_g"] or Decimal("0")),
        "waste_g": _float(usage_totals["waste_g"] or Decimal("0")),
        "material_cost": _float(material_cost),
        "currency": default_currency,
        "foreign_cost_rows_excluded": foreign_cost_rows,
        "printers": printer_rows,
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
        Printer.objects.filter(owner=request.user).select_related(
            "manufacturer",
            "printer_manufacturer",
            "catalog_model__manufacturer",
            "printing_location",
        ).prefetch_related(
            "filament_slots__spool__filament__manufacturer",
            "filament_slots__spool__filament__filament_manufacturer",
            "external_links",
            "live_connections",
        )
    )
    spools = list(
        Spool.objects.filter(owner=request.user).select_related(
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
        Model3D.objects.filter(owner=request.user).select_related("project").prefetch_related(
            "revisions__assets__file_asset__project"
        )
    )
    recent_prints = list(
        PrintJob.objects.filter(owner=request.user).select_related(
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
            "print_jobs": PrintJob.objects.filter(owner=request.user).count(),
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
            for item in PrintingLocation.objects.filter(owner=request.user).order_by("name")
        ],
        "common_filament_materials": COMMON_FILAMENT_MATERIALS,
        "model_files": [
            _serialise_file_asset(asset)
            for asset in FileAsset.objects.filter(owner=request.user).filter(
                category__in=["mesh", "slicer", "cad"],
                superseded_by__isnull=True,
            )
                .select_related("project", "board__manufacturer", "component__category")
                .order_by("category", "name")[:5000]
        ],
        "models": [_serialise_printing_model(model) for model in models_3d],
        "recent_prints": [_serialise_print_job(job) for job in recent_prints],
        "analytics": _printing_analytics(request.user),
        "integrations": [
            _serialise_printing_integration_status(item)
            for item in PrintingIntegrationSetting.objects.filter(owner=request.user).filter(enabled=True).order_by("provider")
        ],
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
@require_http_methods(["GET"])
def printing_filament_catalogue_meta(request):
    try:
        data = spoolmandb_meta()
        data["materials"] = sorted(
            set(COMMON_FILAMENT_MATERIALS) | set(data.get("materials") or []),
            key=str.casefold,
        )
        return JsonResponse(data)
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

        manufacturer, _ = FilamentManufacturer.objects.get_or_create(
            name=data["manufacturer"] or "Generic"
        )
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

        existing = FilamentProduct.objects.select_related(
            "filament_manufacturer", "manufacturer", "source"
        ).filter(source=source).first()
        if existing:
            return JsonResponse({"item": _serialise_filament_product(existing), "created": False})

        existing = FilamentProduct.objects.filter(
            filament_manufacturer=manufacturer,
            name=data["name"],
            material=data["material"],
            diameter_mm=_catalogue_decimal(data["diameter_mm"], "diameter_mm", 2),
            color_hex=data["color_hex"],
        ).first()

        defaults = {
            "source": source,
            "filament_manufacturer": manufacturer,
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
            if not existing.filament_manufacturer_id:
                existing.filament_manufacturer = manufacturer
                changed = True
            for field, value in defaults.items():
                if field in {"source", "filament_manufacturer", "name", "material", "diameter_mm"}:
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

        item = FilamentProduct.objects.select_related(
            "filament_manufacturer", "manufacturer", "source"
        ).get(pk=item.pk)
        return JsonResponse({"item": _serialise_filament_product(item), "created": created}, status=201 if created else 200)
    except FilamentCatalogueError as exc:
        return _error(str(exc), status=502)
    except ValidationError as exc:
        return _validation_response(exc)
    except (ValueError, IntegrityError) as exc:
        return _error(str(exc))


@login_required
@require_http_methods(["GET", "POST"])
def printing_locations(request):
    if request.method == "GET":
        return JsonResponse({
            "rows": [
                _serialise_printing_location(item)
                for item in PrintingLocation.objects.filter(owner=request.user).order_by("name")
            ]
        })

    denied = _require_permission(request, "core.add_printinglocation")
    if denied:
        return denied
    try:
        payload = _read_json(request)
        item = PrintingLocation(
            owner=request.user,
            name=str(payload.get("name") or "").strip(),
            kind=str(payload.get("kind") or "storage").strip(),
            notes=str(payload.get("notes") or "").strip(),
        )
        item.full_clean()
        item.save()
        return JsonResponse({"item": _serialise_printing_location(item)}, status=201)
    except ValidationError as exc:
        return _validation_response(exc)
    except IntegrityError:
        return _error("Location name must be unique.")


@login_required
@require_http_methods(["PATCH", "DELETE"])
def printing_location_detail(request, location_id):
    item = PrintingLocation.objects.filter(owner=request.user).filter(pk=location_id).first()
    if not item:
        return _error("Location not found.", status=404)

    if request.method == "DELETE":
        denied = _require_permission(request, "core.change_printinglocation")
        if denied:
            return denied
        item.delete()
        return JsonResponse({"deleted": True})

    denied = _require_permission(request, "core.change_printinglocation")
    if denied:
        return denied
    try:
        payload = _read_json(request)
        for field in ["name", "kind", "notes"]:
            if field in payload:
                setattr(item, field, str(payload.get(field) or "").strip())
        item.full_clean()
        item.save()
        return JsonResponse({"item": _serialise_printing_location(item)})
    except ValidationError as exc:
        return _validation_response(exc)
    except IntegrityError:
        return _error("Location name must be unique.")


@login_required
@require_http_methods(["GET", "POST"])
def printing_printers(request):
    if request.method == "GET":
        qs = Printer.objects.filter(owner=request.user).select_related(
            "manufacturer",
            "printer_manufacturer",
            "catalog_model__manufacturer",
            "printing_location",
        ).prefetch_related(
            "filament_slots__spool__filament__manufacturer",
            "filament_slots__spool__filament__filament_manufacturer",
            "live_connections",
        )
        return JsonResponse({"rows": [_serialise_printer(item) for item in qs]})

    denied = _require_permission(request, "core.add_printer")
    if denied:
        return denied
    try:
        payload = _read_json(request)
        printer_manufacturer, catalog_model = _resolve_printer_catalogue(payload)
        location = _resolve_printing_location(payload.get("location_id"), request.user)
        model_name = (
            catalog_model.name
            if catalog_model
            else str(payload.get("model") or "").strip()
        )
        if not model_name:
            return _error("Choose a printer model or enter a custom model name.")

        def chosen_decimal(field, catalogue_value=None, default=None):
            raw = payload.get(field)
            if raw not in (None, ""):
                return _parse_decimal(raw, field)
            if catalogue_value is not None:
                return catalogue_value
            return default

        item = Printer(
            owner=request.user,
            name=str(payload.get("name") or model_name).strip(),
            printer_manufacturer=printer_manufacturer,
            catalog_model=catalog_model,
            model=model_name,
            serial_number=str(payload.get("serial_number") or "").strip(),
            printing_location=location,
            is_active=payload.get("is_active") is not False,
            multi_material_installed=bool(payload.get("multi_material_installed", False)),
            connection_host=str(payload.get("connection_host") or "").strip(),
            build_volume_x_mm=chosen_decimal(
                "build_volume_x_mm",
                catalog_model.build_volume_x_mm if catalog_model else None,
            ),
            build_volume_y_mm=chosen_decimal(
                "build_volume_y_mm",
                catalog_model.build_volume_y_mm if catalog_model else None,
            ),
            build_volume_z_mm=chosen_decimal(
                "build_volume_z_mm",
                catalog_model.build_volume_z_mm if catalog_model else None,
            ),
            nozzle_mm=chosen_decimal(
                "nozzle_mm",
                catalog_model.nozzle_mm if catalog_model else None,
                Decimal("0.4"),
            ),
            profile_data={
                "catalogue_features": catalog_model.features if catalog_model else {},
                "multi_material_system": catalog_model.multi_material_system if catalog_model else "",
                "catalogue_source_url": catalog_model.source_url if catalog_model else "",
            },
            notes=str(payload.get("notes") or "").strip(),
        )
        if item.multi_material_installed and (
            not catalog_model or not catalog_model.multi_material_system
        ):
            return _error("This printer model does not have a supported multi-material add-on in the catalogue.")
        item.full_clean()
        item.save()
        item = Printer.objects.filter(owner=request.user).select_related(
            "manufacturer",
            "printer_manufacturer",
            "catalog_model__manufacturer",
            "printing_location",
        ).prefetch_related("filament_slots__spool__filament").get(pk=item.pk)
        return JsonResponse({"item": _serialise_printer(item)}, status=201)
    except ValidationError as exc:
        return _validation_response(exc)


@login_required
@require_http_methods(["PATCH", "DELETE"])
def printing_printer_detail(request, printer_id):
    item = Printer.objects.filter(owner=request.user).select_related(
        "manufacturer",
        "printer_manufacturer",
        "catalog_model__manufacturer",
        "printing_location",
    ).prefetch_related(
        "filament_slots__spool__filament__manufacturer",
        "filament_slots__spool__filament__filament_manufacturer",
        "live_connections",
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
        previous_system = item.catalog_model.multi_material_system if item.catalog_model else ""
        previous_installed = item.multi_material_installed
        if any(key in payload for key in ["catalog_model_id", "printer_manufacturer_id", "manufacturer_id", "manufacturer_name"]):
            maker, catalog_model = _resolve_printer_catalogue(payload)
            item.printer_manufacturer = maker
            item.catalog_model = catalog_model
            item.manufacturer = None
            if catalog_model:
                item.model = catalog_model.name
                item.build_volume_x_mm = catalog_model.build_volume_x_mm
                item.build_volume_y_mm = catalog_model.build_volume_y_mm
                item.build_volume_z_mm = catalog_model.build_volume_z_mm
                item.nozzle_mm = catalog_model.nozzle_mm
                item.profile_data = {
                    **(item.profile_data or {}),
                    "catalogue_features": catalog_model.features or {},
                    "multi_material_system": catalog_model.multi_material_system,
                    "catalogue_source_url": catalog_model.source_url,
                }
                if previous_system != catalog_model.multi_material_system:
                    item.multi_material_installed = False
            else:
                item.multi_material_installed = False
        if "location_id" in payload:
            item.printing_location = _resolve_printing_location(payload.get("location_id"), request.user)
            item.location = ""
        if "is_active" in payload:
            item.is_active = bool(payload.get("is_active"))
        if "multi_material_installed" in payload:
            requested_installed = bool(payload.get("multi_material_installed"))
            if requested_installed and (
                not item.catalog_model or not item.catalog_model.multi_material_system
            ):
                return _error("This printer model does not have a supported multi-material add-on in the catalogue.")
            item.multi_material_installed = requested_installed
        for field in ["name", "model", "serial_number", "connection_host", "notes"]:
            if field in payload:
                setattr(item, field, str(payload.get(field) or "").strip())
        for field in ["build_volume_x_mm", "build_volume_y_mm", "build_volume_z_mm", "nozzle_mm"]:
            if field in payload:
                setattr(item, field, _parse_decimal(payload.get(field), field, allow_none=field != "nozzle_mm"))
        item.full_clean()
        item.save()

        current_system = item.catalog_model.multi_material_system if item.catalog_model else ""
        systems_to_retire = set()
        if previous_installed and (not item.multi_material_installed or previous_system != current_system):
            if previous_system:
                systems_to_retire.add(previous_system)
        for system in systems_to_retire:
            for slot in item.filament_slots.filter(system=system):
                slot.is_loaded = False
                slot.spool = None
                slot.remaining_weight_g = None
                metadata = dict(slot.metadata or {})
                metadata.pop("link_source", None)
                metadata.pop("link_confirmed_at", None)
                metadata.pop("material_fingerprint", None)
                slot.metadata = metadata
                slot.save(update_fields=[
                    "is_loaded", "spool", "remaining_weight_g", "metadata", "updated_at"
                ])

        item = Printer.objects.filter(owner=request.user).select_related(
            "manufacturer",
            "printer_manufacturer",
            "catalog_model__manufacturer",
            "printing_location",
        ).prefetch_related(
            "filament_slots__spool__filament__manufacturer",
            "filament_slots__spool__filament__filament_manufacturer",
            "live_connections",
        ).get(pk=item.pk)
        return JsonResponse({"item": _serialise_printer(item)})
    except ValidationError as exc:
        return _validation_response(exc)


@login_required
@require_http_methods(["GET", "POST"])
def printing_printer_connections(request, printer_id):
    printer = Printer.objects.filter(owner=request.user, pk=printer_id).first()
    if not printer:
        return _error("Printer not found.", status=404)

    if request.method == "GET":
        rows = printer.live_connections.all()
        return JsonResponse({
            "rows": [_serialise_printer_connection(item) for item in rows],
            "adapters": adapter_catalogue(),
        })

    denied = _require_permission(request, "core.change_printer")
    if denied:
        return denied
    try:
        payload = _read_json(request)
        adapter = str(payload.get("adapter") or "").strip()
        definition = PRINTER_ADAPTERS.get(adapter)
        if not definition:
            return _error("Choose a supported MakerVault printer adapter.")

        endpoint_url = str(payload.get("endpoint_url") or "").strip()
        if endpoint_url:
            endpoint_url = normalise_printer_endpoint(endpoint_url)
        interval = int(payload.get("poll_interval_seconds") or 30)
        config = dict(payload.get("config") or {})
        if "api_key" in payload and str(payload.get("api_key") or "").strip():
            config["api_key"] = str(payload.get("api_key") or "").strip()

        item = PrinterConnection(
            printer=printer,
            adapter=adapter,
            enabled=payload.get("enabled") is not False,
            endpoint_url=endpoint_url,
            poll_interval_seconds=interval,
            capabilities=dict(definition.capabilities),
            config=config,
        )
        if not item.enabled:
            item.status = "disabled"
        elif not endpoint_url:
            item.status = "not_configured"
        elif definition.experimental and not definition.supported:
            item.status = "experimental"
        else:
            item.status = "disconnected"
        item.full_clean()
        item.save()
        return JsonResponse({"item": _serialise_printer_connection(item)}, status=201)
    except (ValidationError, ValueError) as exc:
        if isinstance(exc, ValidationError):
            return _validation_response(exc)
        return _error(str(exc))
    except PrinterConnectionError as exc:
        return _error(str(exc))
    except IntegrityError:
        return _error("That printer already has this live adapter.", status=409)


@login_required
@require_http_methods(["PATCH", "DELETE"])
def printing_printer_connection_detail(request, printer_id, connection_id):
    item = PrinterConnection.objects.select_related("printer").filter(
        pk=connection_id,
        printer_id=printer_id,
        printer__owner=request.user,
    ).first()
    if not item:
        return _error("Printer connection not found.", status=404)

    denied = _require_permission(request, "core.change_printer")
    if denied:
        return denied

    if request.method == "DELETE":
        item.delete()
        return JsonResponse({"deleted": True})

    try:
        payload = _read_json(request)
        definition = PRINTER_ADAPTERS.get(item.adapter)
        if "enabled" in payload:
            item.enabled = bool(payload.get("enabled"))
        if "endpoint_url" in payload:
            raw_url = str(payload.get("endpoint_url") or "").strip()
            item.endpoint_url = normalise_printer_endpoint(raw_url) if raw_url else ""
        if "poll_interval_seconds" in payload:
            item.poll_interval_seconds = int(payload.get("poll_interval_seconds"))
        config = dict(item.config or {})
        if "api_key" in payload and str(payload.get("api_key") or "").strip():
            config["api_key"] = str(payload.get("api_key") or "").strip()
        if payload.get("clear_api_key") is True:
            config.pop("api_key", None)
        if "config" in payload and isinstance(payload.get("config"), dict):
            for key, value in payload["config"].items():
                if key not in {"api_key", "token", "password", "access_code"}:
                    config[key] = value
        item.config = config

        if not item.enabled:
            item.status = "disabled"
        elif not item.endpoint_url:
            item.status = "not_configured"
        elif definition and definition.experimental and not definition.supported:
            item.status = "experimental"
        elif item.status in {"disabled", "not_configured", "experimental"}:
            item.status = "disconnected"

        item.full_clean()
        item.save()
        return JsonResponse({"item": _serialise_printer_connection(item)})
    except (ValidationError, ValueError) as exc:
        if isinstance(exc, ValidationError):
            return _validation_response(exc)
        return _error(str(exc))
    except PrinterConnectionError as exc:
        return _error(str(exc))


@login_required
@require_http_methods(["POST"])
def printing_printer_connection_refresh(request, printer_id, connection_id):
    item = PrinterConnection.objects.select_related("printer").filter(
        pk=connection_id,
        printer_id=printer_id,
        printer__owner=request.user,
    ).first()
    if not item:
        return _error("Printer connection not found.", status=404)
    try:
        snapshot = poll_connection(item)
        item.refresh_from_db()
        return JsonResponse({
            "item": _serialise_printer_connection(item),
            "snapshot": snapshot,
        })
    except PrinterConnectionError as exc:
        item.refresh_from_db()
        return JsonResponse({
            "error": str(exc),
            "item": _serialise_printer_connection(item),
        }, status=502)


@login_required
@require_http_methods(["GET", "POST"])
def printing_spools(request):
    if request.method == "GET":
        qs = Spool.objects.filter(owner=request.user).select_related(
            "filament__manufacturer",
            "filament__filament_manufacturer",
            "storage_location",
            "assigned_printer",
        ).prefetch_related(
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

        storage_location = _resolve_printing_location(
            payload.get("storage_location_id"), request.user, "storage_location_id"
        )
        assigned_printer = None
        if payload.get("assigned_printer_id"):
            assigned_printer = Printer.objects.filter(owner=request.user).filter(pk=payload.get("assigned_printer_id")).first()
            if not assigned_printer:
                return _error("Selected printer was not found.")
        if storage_location and assigned_printer:
            return _error("Choose either a storage location or a printer.")

        rfid_uid = str(payload.get("rfid_uid") or "").strip().upper()
        if rfid_uid and Spool.objects.filter(owner=request.user).filter(rfid_uid=rfid_uid).exists():
            return _error("That RFID tag ID is already assigned to another MakerVault spool.", status=409)

        item = Spool(
            owner=request.user,
            spool_id=next_spool_id(request.user),
            rfid_uid=rfid_uid,
            filament=filament,
            initial_weight_g=_parse_decimal(payload.get("initial_weight_g"), "initial_weight_g"),
            remaining_weight_g=_parse_decimal(payload.get("remaining_weight_g"), "remaining_weight_g"),
            purchase_cost=_parse_decimal(payload.get("purchase_cost"), "purchase_cost"),
            currency=str(payload.get("currency") or settings.MAKERVAULT_CURRENCY).upper()[:3],
            storage_location=storage_location,
            assigned_printer=assigned_printer,
            location=str(payload.get("location") or "").strip() if not (storage_location or assigned_printer) else "",
            status=str(payload.get("status") or "sealed"),
            opened_on=_parse_date(payload.get("opened_on"), "opened_on"),
            notes=str(payload.get("notes") or "").strip(),
        )
        item.full_clean()
        item.save()
        item = Spool.objects.filter(owner=request.user).select_related(
            "filament__manufacturer",
            "filament__filament_manufacturer",
            "storage_location",
            "assigned_printer",
        ).prefetch_related("external_links", "printer_slots__printer").get(pk=item.pk)
        return JsonResponse({"item": _serialise_spool(item)}, status=201)
    except ValidationError as exc:
        return _validation_response(exc)
    except IntegrityError:
        return _error("MakerVault could not allocate a unique spool ID; please retry.")


def _link_discovered_provider_spool(slot, spool):
    if slot.system != "simplyprint":
        return
    external_id = str((slot.metadata or {}).get("external_spool_id") or "").strip()
    if not external_id:
        return

    existing_remote = ExternalSpoolLink.objects.filter(
        provider="simplyprint",
        external_id=external_id,
    ).first()
    if existing_remote and existing_remote.spool_id != spool.id:
        raise ValidationError({
            "existing_spool_id": (
                f"SimplyPrint filament {external_id} is already linked to "
                f"{existing_remote.spool.spool_id}."
            )
        })

    existing_local = ExternalSpoolLink.objects.filter(
        provider="simplyprint",
        spool=spool,
    ).exclude(external_id=external_id).first()
    if existing_local:
        raise ValidationError({
            "existing_spool_id": (
                f"{spool.spool_id} is already linked to SimplyPrint filament "
                f"{existing_local.external_id}."
            )
        })

    ExternalSpoolLink.objects.update_or_create(
        provider="simplyprint",
        external_id=external_id,
        defaults={
            "spool": spool,
            "sync_direction": "import",
            "last_synced_at": timezone.now(),
            "sync_metadata": {
                "linked_from_slot": str(slot.id),
                "remote_uid": (slot.metadata or {}).get("remote_uid", ""),
                "nfc_id": (slot.metadata or {}).get("nfc_id", ""),
            },
        },
    )


@login_required
@require_http_methods(["POST"])
def printing_slot_add_to_inventory(request, slot_id):
    """Explicitly link or create a physical spool for a provider-discovered slot."""
    denied = _require_permission(request, "core.add_spool")
    if denied:
        return denied

    slot = PrinterFilamentSlot.objects.select_related(
        "printer",
        "spool__filament",
    ).filter(pk=slot_id, printer__owner=request.user).first()
    if not slot:
        return _error("Discovered filament slot not found.", status=404)
    if not slot.is_loaded:
        return _error("That filament slot is no longer loaded.", status=409)
    if slot.spool_id:
        return _error(
            f"That slot is already linked to {slot.spool.spool_id}.",
            status=409,
        )

    try:
        payload = _read_json(request)
        existing_spool_id = str(payload.get("existing_spool_id") or "").strip()

        if existing_spool_id:
            change_denied = _require_permission(request, "core.change_spool")
            if change_denied:
                return change_denied

            with transaction.atomic():
                spool = Spool.objects.filter(owner=request.user).select_for_update().filter(
                    pk=existing_spool_id
                ).first()
                if not spool:
                    return _error("Selected MakerVault spool was not found.", status=404)

                other_loaded = PrinterFilamentSlot.objects.filter(
                    spool=spool,
                    is_loaded=True,
                ).exclude(pk=slot.pk).select_related("printer").first()
                if other_loaded:
                    return _error(
                        f"{spool.spool_id} is already linked to a loaded slot on {other_loaded.printer.name}.",
                        status=409,
                    )

                spool.assigned_printer = slot.printer
                spool.storage_location = None
                spool.location = ""
                spool.full_clean()
                spool.save(update_fields=[
                    "assigned_printer", "storage_location", "location", "updated_at"
                ])
                _link_discovered_provider_spool(slot, spool)

                metadata = dict(slot.metadata or {})
                metadata["link_source"] = "user_linked_existing"
                metadata["link_confirmed_at"] = timezone.now().isoformat()
                slot.spool = spool
                slot.metadata = metadata
                slot.save(update_fields=["spool", "metadata", "updated_at"])

            spool = Spool.objects.filter(owner=request.user).select_related(
                "filament__manufacturer",
                "filament__filament_manufacturer",
                "storage_location",
                "assigned_printer",
            ).prefetch_related("external_links", "printer_slots__printer").get(pk=spool.pk)
            slot = PrinterFilamentSlot.objects.select_related(
                "printer", "spool__filament"
            ).get(pk=slot.pk)
            return JsonResponse({
                "item": _serialise_spool(spool),
                "slot": _serialise_printer_slot(slot),
                "created_filament": False,
                "linked_existing": True,
            })

        created_filament = False
        rfid_uid = str(payload.get("rfid_uid") or slot.rfid_uid or "").strip().upper()
        if rfid_uid:
            existing_rfid_spool = Spool.objects.filter(owner=request.user).filter(rfid_uid=rfid_uid).first()
            if existing_rfid_spool:
                return _error(
                    f"RFID tag {rfid_uid} already belongs to {existing_rfid_spool.spool_id}.",
                    status=409,
                )

        with transaction.atomic():
            filament = None
            if payload.get("filament_id"):
                filament = FilamentProduct.objects.filter(pk=payload.get("filament_id")).first()
                if not filament:
                    return _error("Selected filament product was not found.")
            else:
                filament_denied = _require_permission(request, "core.add_filamentproduct")
                if filament_denied:
                    return filament_denied

                filament_payload = payload.get("new_filament")
                if not isinstance(filament_payload, dict):
                    return _error("Choose an existing filament or provide the detected filament details.")

                manufacturer = _resolve_filament_manufacturer(filament_payload)
                name = str(
                    filament_payload.get("name")
                    or (slot.metadata or {}).get("product_name")
                    or slot.material
                    or "Detected filament"
                ).strip()
                material = str(
                    filament_payload.get("material")
                    or slot.material
                    or ""
                ).strip()
                if not material:
                    return _error("Material is required for a new filament product.")

                filament = FilamentProduct(
                    filament_manufacturer=manufacturer,
                    name=name,
                    material=material,
                    color_name=str(filament_payload.get("color_name") or "").strip(),
                    color_hex=str(
                        filament_payload.get("color_hex")
                        or slot.color_hex
                        or ""
                    ).strip(),
                    transparency=str(filament_payload.get("transparency") or "opaque").strip(),
                    diameter_mm=_parse_decimal(
                        filament_payload.get("diameter_mm", "1.75"),
                        "diameter_mm",
                        allow_none=False,
                    ),
                    nominal_weight_g=_parse_decimal(
                        filament_payload.get("nominal_weight_g"),
                        "nominal_weight_g",
                    ),
                    profile_data={
                        "discovered_from": {
                            "system": slot.system,
                            "system_label": slot.get_system_display(),
                            "printer_id": str(slot.printer_id),
                            "printer": slot.printer.name,
                            "external_ref": slot.external_ref,
                            "physical_tag_uid": slot.rfid_uid,
                            "material_code": (slot.metadata or {}).get("material_code", ""),
                            "vendor": (slot.metadata or {}).get("vendor", ""),
                            "product_name": (slot.metadata or {}).get("product_name", ""),
                        }
                    },
                )
                filament.full_clean()
                filament.save()
                created_filament = True

            initial_weight = _parse_decimal(payload.get("initial_weight_g"), "initial_weight_g")
            remaining_weight = _parse_decimal(payload.get("remaining_weight_g"), "remaining_weight_g")
            if remaining_weight is None and initial_weight is not None:
                detected_percent = (slot.metadata or {}).get("remaining_percent")
                try:
                    percent = Decimal(str(detected_percent)) if detected_percent is not None else None
                except (InvalidOperation, TypeError, ValueError):
                    percent = None
                if percent is not None and Decimal("0") <= percent <= Decimal("100"):
                    remaining_weight = (
                        initial_weight * percent / Decimal("100")
                    ).quantize(Decimal("0.01"))

            spool = Spool(
                owner=slot.printer.owner or request.user,
                spool_id=next_spool_id(slot.printer.owner),
                rfid_uid=rfid_uid,
                filament=filament,
                initial_weight_g=initial_weight,
                remaining_weight_g=remaining_weight,
                purchase_cost=_parse_decimal(payload.get("purchase_cost"), "purchase_cost"),
                currency=str(payload.get("currency") or settings.MAKERVAULT_CURRENCY).upper()[:3],
                assigned_printer=slot.printer,
                status=str(payload.get("status") or "open"),
                opened_on=_parse_date(payload.get("opened_on"), "opened_on"),
                notes=str(payload.get("notes") or "").strip(),
            )
            spool.full_clean()
            spool.save()
            _link_discovered_provider_spool(slot, spool)

            metadata = dict(slot.metadata or {})
            metadata["link_source"] = "inventory_created_from_slot"
            metadata["link_confirmed_at"] = timezone.now().isoformat()
            slot.spool = spool
            slot.metadata = metadata
            if remaining_weight is not None:
                slot.remaining_weight_g = remaining_weight
            slot.save(update_fields=[
                "spool", "metadata", "remaining_weight_g", "updated_at"
            ])

        spool = Spool.objects.filter(owner=request.user).select_related(
            "filament__manufacturer",
            "filament__filament_manufacturer",
            "storage_location",
            "assigned_printer",
        ).prefetch_related("external_links", "printer_slots__printer").get(pk=spool.pk)
        slot = PrinterFilamentSlot.objects.select_related(
            "printer",
            "spool__filament",
        ).get(pk=slot.pk)
        return JsonResponse({
            "item": _serialise_spool(spool),
            "slot": _serialise_printer_slot(slot),
            "created_filament": created_filament,
            "linked_existing": False,
        }, status=201)
    except ValidationError as exc:
        return _validation_response(exc)
    except IntegrityError:
        return _error("MakerVault could not create or link the detected spool; please retry.")




@login_required
@require_http_methods(["PATCH", "DELETE"])
def printing_spool_detail(request, spool_id):
    item = Spool.objects.filter(owner=request.user).select_related(
        "filament__manufacturer",
        "filament__filament_manufacturer",
        "storage_location",
        "assigned_printer",
    ).prefetch_related(
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
        if "rfid_uid" in payload:
            rfid_uid = str(payload.get("rfid_uid") or "").strip().upper()
            if rfid_uid and Spool.objects.filter(owner=request.user).exclude(pk=item.pk).filter(rfid_uid=rfid_uid).exists():
                return _error("That RFID tag ID is already assigned to another MakerVault spool.", status=409)
            item.rfid_uid = rfid_uid
        if "storage_location_id" in payload:
            item.storage_location = _resolve_printing_location(
                payload.get("storage_location_id"), request.user, "storage_location_id"
            )
            if item.storage_location:
                item.assigned_printer = None
                item.location = ""
        if "assigned_printer_id" in payload:
            printer_id = payload.get("assigned_printer_id")
            item.assigned_printer = Printer.objects.filter(owner=request.user).filter(pk=printer_id).first() if printer_id else None
            if printer_id and not item.assigned_printer:
                return _error("Selected printer was not found.")
            if item.assigned_printer:
                item.storage_location = None
                item.location = ""
        for field in ["status", "currency", "notes"]:
            if field in payload:
                value = str(payload.get(field) or "").strip()
                setattr(item, field, value.upper()[:3] if field == "currency" else value)
        if "location" in payload and not item.storage_location_id and not item.assigned_printer_id:
            item.location = str(payload.get("location") or "").strip()
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
        return _error("Spool ID and RFID tag ID must be unique.")


@login_required
@require_http_methods(["GET", "POST"])
def printing_models(request):
    if request.method == "GET":
        qs = Model3D.objects.filter(owner=request.user).select_related("project").prefetch_related(
            "revisions__assets__file_asset__project"
        )
        return JsonResponse({"rows": [_serialise_printing_model(item) for item in qs]})

    denied = _require_permission(request, "core.add_model3d")
    if denied:
        return denied

    uploaded = request.FILES.get("file")
    if uploaded:
        file_denied = _require_permission(request, "core.add_fileasset")
        if file_denied:
            return file_denied
        payload = request.POST
        project = None
        project_id = str(payload.get("project_id") or "").strip()
        if project_id:
            project = Project.objects.filter(owner=request.user).filter(pk=project_id).first()
            if not project:
                return _error("Selected project was not found.")
            project_denied = _require_permission(request, "core.change_project")
            if project_denied:
                return project_denied

        original_name = Path(uploaded.name or "model").name
        extension = Path(original_name).suffix.lower()
        category = {" .stl": "mesh"}.get(extension)
        if extension == ".stl":
            category = "mesh"
        elif extension == ".3mf":
            category = "slicer"
        else:
            return _error("Choose an STL or 3MF file.")

        model_name = str(payload.get("name") or Path(original_name).stem).strip()
        revision_version = str(payload.get("revision_version") or "1.0").strip()
        if not revision_version:
            return _error("Revision version is required.")
        try:
            ensure_storage_capacity(request.user, getattr(uploaded, "size", 0) or 0)
        except StorageQuotaExceeded as exc:
            return _storage_quota_response(request, exc)

        stored_asset = None
        try:
            checksum = _sha256_upload(uploaded)
            with transaction.atomic():
                item = Model3D(
                    owner=request.user,
                    project=project,
                    name=model_name,
                    description=str(payload.get("description") or "").strip(),
                    source_url=str(payload.get("source_url") or "").strip(),
                    license=str(payload.get("license") or "").strip(),
                    tags=_normalise_tags(payload.get("tags")),
                )
                item.full_clean()
                item.save()

                revision = ModelRevision(
                    model=item,
                    version=revision_version,
                    notes=str(payload.get("revision_notes") or "").strip(),
                )
                revision.full_clean()
                revision.save()

                stored_asset = FileAsset(
                    owner=request.user,
                    project=project,
                    category=category,
                    name=str(payload.get("file_name") or original_name).strip()[:255],
                    version=revision_version[:80],
                    description=str(payload.get("file_description") or "").strip(),
                    sha256=checksum,
                    metadata={
                        "original_name": original_name,
                        "size_bytes": getattr(uploaded, "size", 0) or 0,
                        "extension": extension,
                        "uploaded_from": "printing_model",
                    },
                )
                stored_asset.file = uploaded
                stored_asset.full_clean()
                stored_asset.save()

                link = ModelRevisionAsset(
                    revision=revision,
                    file_asset=stored_asset,
                    role="slicer" if category == "slicer" else "model",
                    is_primary=True,
                )
                link.full_clean()
                link.save()

            _analyse_revision_link(revision, link)
            item = Model3D.objects.filter(owner=request.user).select_related("project").prefetch_related(
                "revisions__assets__file_asset__project"
            ).get(pk=item.pk)
            return JsonResponse({"item": _serialise_printing_model(item)}, status=201)
        except ValidationError as exc:
            if stored_asset and stored_asset.file:
                try:
                    stored_asset.file.delete(save=False)
                except OSError:
                    pass
            return _validation_response(exc)
        except IntegrityError:
            if stored_asset and stored_asset.file:
                try:
                    stored_asset.file.delete(save=False)
                except OSError:
                    pass
            return _error("A matching model revision already exists.")

    try:
        payload = _read_json(request)
        project = None
        if payload.get("project_id"):
            project = Project.objects.filter(owner=request.user).filter(pk=payload["project_id"]).first()
            if not project:
                return _error("Selected project was not found.")
        item = Model3D(
            owner=request.user,
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
    item = Model3D.objects.filter(owner=request.user).select_related("project").prefetch_related(
        "revisions__assets__file_asset__project"
    ).filter(pk=model_id).first()
    if not item:
        return _error("3D model not found.", status=404)
    if request.method == "DELETE":
        denied = _require_permission(request, "core.delete_model3d")
        if denied:
            return denied
        try:
            item.delete()
            return JsonResponse({"deleted": True})
        except ProtectedError:
            return _error(
                "This model is referenced by protected records and cannot be deleted.",
                status=409,
            )

    denied = _require_permission(request, "core.change_model3d")
    if denied:
        return denied
    try:
        payload = _read_json(request)
        if "project_id" in payload:
            project_id = payload.get("project_id")
            item.project = Project.objects.filter(owner=request.user).filter(pk=project_id).first() if project_id else None
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
    model = Model3D.objects.filter(owner=request.user).filter(pk=model_id).first()
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
        model = Model3D.objects.filter(owner=request.user).select_related("project").prefetch_related(
            "revisions__assets__file_asset__project"
        ).get(pk=model.pk)
        return JsonResponse({"model": _serialise_printing_model(model)}, status=201)
    except ValidationError as exc:
        return _validation_response(exc)
    except IntegrityError:
        return _error("That revision version already exists for this model.")


@login_required
@require_http_methods(["POST"])
def printing_model_revision_upload(request, model_id):
    model = Model3D.objects.filter(owner=request.user).select_related("project").filter(pk=model_id).first()
    if not model:
        return _error("3D model not found.", status=404)

    denied = _require_permission(request, "core.change_model3d")
    if denied:
        return denied
    file_denied = _require_permission(request, "core.add_fileasset")
    if file_denied:
        return file_denied
    if model.project:
        project_denied = _require_permission(request, "core.change_project")
        if project_denied:
            return project_denied

    uploaded = request.FILES.get("file")
    if not uploaded:
        return _error("Choose an STL or 3MF file to upload.")

    original_name = Path(uploaded.name or "model").name
    extension = Path(original_name).suffix.lower()
    if extension == ".stl":
        category = "mesh"
        role = "model"
    elif extension == ".3mf":
        category = "slicer"
        role = "slicer"
    else:
        return _error("Choose an STL or 3MF file.")

    version = str(request.POST.get("version") or "").strip()[:80]
    if not version:
        return _error("Revision version is required.")
    if ModelRevision.objects.filter(model=model, version=version).exists():
        return _error("That revision version already exists for this model.")
    try:
        ensure_storage_capacity(request.user, getattr(uploaded, "size", 0) or 0)
    except StorageQuotaExceeded as exc:
        return _storage_quota_response(request, exc)

    previous_link = (
        ModelRevisionAsset.objects.filter(
            revision__model=model,
            is_primary=True,
            role__in=["model", "slicer"],
        )
        .select_related("file_asset", "revision")
        .order_by("-revision__created_at", "-created_at")
        .first()
    )
    predecessor = previous_link.file_asset if previous_link else None
    if predecessor and FileAsset.objects.filter(owner=request.user).filter(supersedes=predecessor).exists():
        predecessor = None

    stored_asset = None
    try:
        checksum = _sha256_upload(uploaded)
        with transaction.atomic():
            revision = ModelRevision(
                model=model,
                version=version,
                notes=str(request.POST.get("notes") or "").strip(),
            )
            revision.full_clean()
            revision.save()

            stored_asset = FileAsset(
                owner=model.owner or request.user,
                project=model.project,
                category=category,
                name=str(request.POST.get("name") or (previous_link.file_asset.name if previous_link else Path(original_name).stem)).strip()[:255],
                version=version,
                description=str(request.POST.get("description") or "").strip(),
                sha256=checksum,
                metadata={
                    "original_name": original_name,
                    "size_bytes": getattr(uploaded, "size", 0) or 0,
                    "extension": extension,
                    "uploaded_from": "printing_model_revision",
                    "supersedes_id": str(predecessor.id) if predecessor else "",
                },
                supersedes=predecessor,
            )
            stored_asset.file = uploaded
            stored_asset.full_clean()
            stored_asset.save()

            link = ModelRevisionAsset(
                revision=revision,
                file_asset=stored_asset,
                role=role,
                is_primary=True,
            )
            link.full_clean()
            link.save()

        _analyse_revision_link(revision, link)
        model = Model3D.objects.filter(owner=request.user).select_related("project").prefetch_related(
            "revisions__assets__file_asset__project"
        ).get(pk=model.pk)
        return JsonResponse({"model": _serialise_printing_model(model)}, status=201)
    except ValidationError as exc:
        if stored_asset and stored_asset.file:
            try:
                stored_asset.file.delete(save=False)
            except OSError:
                pass
        return _validation_response(exc)
    except IntegrityError:
        if stored_asset and stored_asset.file:
            try:
                stored_asset.file.delete(save=False)
            except OSError:
                pass
        return _error("That revision version already exists for this model.")


@login_required
@require_http_methods(["PATCH", "DELETE"])
def printing_model_revision_detail(request, model_id, revision_id):
    model = Model3D.objects.filter(owner=request.user).filter(pk=model_id).first()
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
    model = Model3D.objects.filter(owner=request.user).select_related("project").filter(pk=model_id).first()
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
        asset = FileAsset.objects.filter(owner=request.user).select_related("project").filter(pk=payload.get("file_asset_id")).first()
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

        if link.is_primary and link.role in {"model", "slicer"}:
            _analyse_revision_link(revision, link)
        model = Model3D.objects.filter(owner=request.user).select_related("project").prefetch_related(
            "revisions__assets__file_asset__project"
        ).get(pk=model.pk)
        return JsonResponse({"model": _serialise_printing_model(model)}, status=201)
    except ValidationError as exc:
        return _validation_response(exc)
    except IntegrityError:
        return _error("That file is already attached to this revision.")


@login_required
@require_http_methods(["POST"])
def printing_revision_analyse(request, model_id, revision_id):
    model = Model3D.objects.filter(owner=request.user).filter(pk=model_id).first()
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
    except ValueError as exc:
        return _error(str(exc))

    link = _select_revision_analysis_link(revision, payload.get("file_asset_id"))
    if not link:
        return _error("Attach an STL or 3MF file to this revision before analysing it.", status=409)

    metadata = _analyse_revision_link(revision, link)
    if metadata.get("analysis_status") == "error":
        return _error(metadata.get("analysis_error") or "Model analysis failed.", status=422)

    return JsonResponse({
        "analysis": metadata.get("analysis") or {},
        "revision_id": str(revision.id),
        "model_id": str(model.id),
    })


@login_required
@require_http_methods(["DELETE"])
def printing_revision_asset_detail(request, model_id, revision_id, link_id):
    model = Model3D.objects.filter(owner=request.user).filter(pk=model_id).first()
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
        spool = Spool.objects.select_related("filament").filter(owner=job.owner, pk=payload["spool_id"]).first()
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

    used_g = _parse_decimal(payload.get("used_g", 0), "used_g", allow_none=False)
    waste_g = _parse_decimal(payload.get("waste_g", 0), "waste_g", allow_none=False)
    explicit_cost = _parse_decimal(payload.get("material_cost"), "material_cost")
    currency = str(payload.get("currency") or (spool.currency if spool else settings.MAKERVAULT_CURRENCY)).upper()[:3]
    estimated_cost = _estimated_spool_material_cost(spool, used_g, waste_g)
    if explicit_cost is None and spool and spool.currency == currency:
        explicit_cost = estimated_cost

    usage = PrintMaterialUsage(
        print_job=job,
        spool=spool,
        filament=filament,
        printer_slot=slot,
        used_g=used_g,
        waste_g=waste_g,
        material_cost=explicit_cost,
        currency=currency,
        notes=str(payload.get("notes") or "").strip(),
        source_metadata={
            "material_cost_source": (
                "spool_purchase_cost" if explicit_cost is not None and payload.get("material_cost") in (None, "") and estimated_cost is not None
                else "manual" if explicit_cost is not None
                else ""
            )
        },
    )
    usage.full_clean()
    return usage


@login_required
@require_http_methods(["GET", "POST"])
def printing_jobs(request):
    if request.method == "GET":
        qs = PrintJob.objects.filter(owner=request.user).select_related(
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
        printer = Printer.objects.filter(owner=request.user).filter(pk=payload.get("printer_id")).first()
        if not printer:
            return _error("Choose a printer.")

        project = None
        if payload.get("project_id"):
            project = Project.objects.filter(owner=request.user).filter(pk=payload["project_id"]).first()
            if not project:
                return _error("Selected project was not found.")

        revision = None
        if payload.get("model_revision_id"):
            revision = ModelRevision.objects.select_related("model").filter(pk=payload["model_revision_id"], model__owner=request.user).first()
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
                owner=request.user,
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

        job = PrintJob.objects.filter(owner=request.user).select_related(
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
    job = PrintJob.objects.filter(owner=request.user).select_related(
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
        "is_superuser": request.user.is_superuser,
        "user_id": request.user.pk,
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
            "add_printing_location": request.user.has_perm("core.add_printinglocation"),
            "change_printing_location": request.user.has_perm("core.change_printinglocation"),
            "add_filament": request.user.has_perm("core.add_filamentproduct"),
            "change_filament": request.user.has_perm("core.change_filamentproduct"),
            "add_spool": request.user.has_perm("core.add_spool"),
            "change_spool": request.user.has_perm("core.change_spool"),
            "delete_spool": request.user.has_perm("core.delete_spool"),
            "add_model3d": request.user.has_perm("core.add_model3d"),
            "change_model3d": request.user.has_perm("core.change_model3d"),
            "delete_model3d": request.user.has_perm("core.delete_model3d"),
            "add_printjob": request.user.has_perm("core.add_printjob"),
            "change_printjob": request.user.has_perm("core.change_printjob"),
            "add_maker_tag": request.user.has_perm("core.add_makertag"),
            "change_maker_tag": request.user.has_perm("core.change_makertag"),
            "add_wiring_diagram": request.user.has_perm("core.add_wiringdiagram"),
            "change_wiring_diagram": request.user.has_perm("core.change_wiringdiagram"),
            "delete_wiring_diagram": request.user.has_perm("core.delete_wiringdiagram"),
        },
        "importers": ["ESPBoards.dev"],
    })
