"""Explicit physical-part inventory. Filament accounting stays on PrintJob."""
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Sum
from django.http import JsonResponse
from django.views.decorators.http import require_http_methods

from .api_views import _error, _read_json, _require_permission, _validation_response, _parse_positive_int, _serialise_print_job
from .models import PrintedPart, PrintedPartEvent, PrintJob, ModelRevision, Project, PrintingLocation


def rows(owner):
    return PrintedPart.objects.filter(owner=owner).select_related("print_job__printer", "print_job__model_revision__model", "model_revision__model", "project", "location", "replaces").prefetch_related("print_job__material_usages")


def serialise(part, events=False):
    production = dict(part.production or {})
    if part.print_job_id:
        job = _serialise_print_job(part.print_job)
        production.update({key: job.get(key) for key in ("filament_used_g", "filament_usage_source", "filament_usage_estimated", "waste_g", "material_cost", "material_usages")})
    result = {
        "id": str(part.id), "name": part.name, "quantity": part.quantity,
        "status": part.status, "status_label": part.get_status_display(),
        "print_job_id": str(part.print_job_id) if part.print_job_id else None,
        "model_revision_id": str(part.model_revision_id) if part.model_revision_id else None,
        "model": part.model_revision.model.name if part.model_revision_id else production.get("model", ""),
        "revision": part.model_revision.version if part.model_revision_id else production.get("revision", ""),
        "project_id": str(part.project_id) if part.project_id else None, "project": part.project.name if part.project_id else "",
        "location_id": str(part.location_id) if part.location_id else None, "location": part.location.name if part.location_id else "",
        "replaces_id": str(part.replaces_id) if part.replaces_id else None, "replaces": part.replaces.name if part.replaces_id else "",
        "production": production, "notes": part.notes, "created_at": part.created_at.isoformat(),
    }
    if events:
        result["events"] = [{"id": event.id, "changes": event.changes, "created_at": event.created_at.isoformat()} for event in part.events.all()[:100]]
    return result


def relation(owner, model, value, field):
    if not value:
        return None
    filters = {"model__owner": owner} if model == ModelRevision else {"owner": owner}
    obj = model.objects.filter(pk=value, **filters).first()
    if not obj:
        raise ValidationError({field: "Selected record was not found."})
    return obj


def apply_fields(part, payload):
    for field in ("name", "status", "notes"):
        if field in payload:
            setattr(part, field, str(payload.get(field) or "").strip())
    if "quantity" in payload:
        part.quantity = _parse_positive_int(payload["quantity"], "quantity", allow_none=False)
    for field, model in (("project", Project), ("location", PrintingLocation), ("replaces", PrintedPart)):
        if field + "_id" in payload:
            setattr(part, field, relation(part.owner, model, payload[field + "_id"], field))


def allocation_check(part):
    if not part.print_job_id:
        return
    # Lock the shared job before reading all retained batches, including retired ones.
    job = PrintJob.objects.select_for_update().get(pk=part.print_job_id, owner=part.owner)
    retained = PrintedPart.objects.filter(print_job=job).exclude(pk=part.pk).aggregate(total=Sum("quantity"))["total"] or 0
    if retained + part.quantity > job.quantity:
        raise ValidationError({"quantity": "Parts already retained plus this quantity exceed the print job quantity. Correct the print job quantity first."})


@login_required
@require_http_methods(["GET", "POST"])
def printed_parts(request):
    if request.method == "GET":
        qs = rows(request.user)
        if request.GET.get("project_id"):
            try:
                project = relation(request.user, Project, request.GET["project_id"], "project")
            except (ValidationError, ValueError, TypeError):
                return _error("Project not found.", 404)
            qs = qs.filter(project=project)
        return JsonResponse({"rows": [serialise(part) for part in qs[:2000]], "statuses": list(PrintedPart.STATUSES)})
    denied = _require_permission(request, "core.add_printedpart")
    if denied:
        return denied
    try:
        payload = _read_json(request)
        with transaction.atomic():
            part = PrintedPart(owner=request.user)
            if payload.get("print_job_id"):
                job = PrintJob.objects.select_for_update().filter(owner=request.user, pk=payload["print_job_id"]).first()
                if not job:
                    return _error("Print job not found.", 404)
                if job.status != "success":
                    return _error("Only successful prints can create retained parts.")
                if payload.get("print_job_quantity") not in (None, ""):
                    count = _parse_positive_int(payload["print_job_quantity"], "print_job_quantity", allow_none=False)
                    if count != job.quantity:
                        denied = _require_permission(request, "core.change_printjob")
                        if denied:
                            return denied
                        job.quantity = count
                        job.full_clean()
                        job.save(update_fields=["quantity", "updated_at"])
                part.print_job = job
                part.model_revision = job.model_revision
                part.project = job.project
                job_data = _serialise_print_job(job)
                part.name = job_data.get("model") or job_data.get("filename") or "Printed part"
                part.production = {**job_data, "scope": "whole_print_job", "currency": job.currency}
            elif payload.get("model_revision_id"):
                part.model_revision = relation(request.user, ModelRevision, payload["model_revision_id"], "model_revision")
            apply_fields(part, payload)
            part.full_clean()
            allocation_check(part)
            part.save()
            PrintedPartEvent.objects.create(part=part, changed_by=request.user, changes={"created": {"name": part.name, "quantity": part.quantity, "status": part.status}})
        return JsonResponse({"part": serialise(rows(request.user).get(pk=part.pk), events=True)}, status=201)
    except (ValidationError, ValueError, TypeError) as exc:
        return _validation_response(exc) if isinstance(exc, ValidationError) else _error("Invalid part fields.")


@login_required
@require_http_methods(["GET", "PATCH"])
def printed_part_detail(request, part_id):
    if request.method == "GET":
        part = rows(request.user).filter(pk=part_id).first()
        return JsonResponse({"part": serialise(part, events=True)}) if part else _error("Printed part not found.", 404)
    denied = _require_permission(request, "core.change_printedpart")
    if denied:
        return denied
    try:
        with transaction.atomic():
            # Lock the job first (same order as creation) to serialize allocation edits.
            part = rows(request.user).filter(pk=part_id).first()
            if not part:
                return _error("Printed part not found.", 404)
            if part.print_job_id:
                PrintJob.objects.select_for_update().get(pk=part.print_job_id)
            part = PrintedPart.objects.select_for_update().get(pk=part.pk)
            before = {field: str(getattr(part, field)) if getattr(part, field) is not None else None for field in ("name", "quantity", "status", "project_id", "location_id", "replaces_id", "notes")}
            apply_fields(part, _read_json(request))
            part.full_clean()
            allocation_check(part)
            changes = {field: {"from": value, "to": str(getattr(part, field)) if getattr(part, field) is not None else None} for field, value in before.items() if value != (str(getattr(part, field)) if getattr(part, field) is not None else None)}
            if changes:
                part.save()
                PrintedPartEvent.objects.create(part=part, changed_by=request.user, changes=changes)
        return JsonResponse({"part": serialise(rows(request.user).get(pk=part.pk), events=True)})
    except (ValidationError, ValueError, TypeError) as exc:
        return _validation_response(exc) if isinstance(exc, ValidationError) else _error("Invalid part fields.")
