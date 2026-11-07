"""Owner-scoped slicer drafts and engine discovery; no execution endpoints yet."""
import json
import os
import math
import re
import uuid
from decimal import Decimal, InvalidOperation

from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.db import IntegrityError, transaction
from django.views.decorators.http import require_http_methods

from .models import FileAsset, Printer, SliceJob, Spool, SlicerProfile
from .slicer_engines import engine_catalogue, get_engine
from .slicer_profiles import SlicerProfileError, inspect_native_profile
from .slicer_profile_lineage import inspect_orca_lineage
from .slicer_mesh import inspect_stl, MeshInspectionError, MAX_INSPECTION_BYTES
from .slicer_bed import inspect_orca_plate
from .slicer_official_profiles import (
    OfficialProfileError, search_official_profiles, fetch_official_profile,
    ENGINE_VERSION as OFFICIAL_ORCA_VERSION, SOURCE as OFFICIAL_ORCA_SOURCE,
    REF as OFFICIAL_ORCA_REF,
)
from django.core.files.base import ContentFile
from .slicer_execution import (
    SlicerExecutionError, verified_installation, validate_scheduling, queue_draft,
)


def _error(message, status=400):
    return JsonResponse({"error": message}, status=status)


def _rows(user):
    return SliceJob.objects.filter(owner=user).select_related(
        "input_asset", "printer", "spool", "output_asset",
        "printer_profile", "filament_profile", "process_profile"
    )


def serialise(job, installed=None):
    can_slice = False
    if installed:
        try:
            can_slice = validate_scheduling(job, installed)
        except (SlicerExecutionError, ValueError):
            pass
    return {
        "id": str(job.id),
        "status": job.status,
        "can_slice": can_slice,
        "progress": job.progress,
        "engine": job.engine,
        "engine_version": job.engine_version,
        "printer_preset": job.printer_preset,
        "filament_preset": job.filament_preset,
        "process_preset": job.process_preset,
        "nozzle_mm": str(job.nozzle_mm),
        "plate": job.plate,
        "settings": job.settings,
        "printer_profile_id": str(job.printer_profile_id) if job.printer_profile_id else None,
        "filament_profile_id": str(job.filament_profile_id) if job.filament_profile_id else None,
        "process_profile_id": str(job.process_profile_id) if job.process_profile_id else None,
        "input_asset": {"id": str(job.input_asset_id), "name": job.input_asset.name},
        "printer": {"id": str(job.printer_id), "name": job.printer.name},
        "spool": {"id": str(job.spool_id), "name": job.spool.spool_id} if job.spool_id else None,
        "output_asset_id": str(job.output_asset_id) if job.output_asset_id else None,
        "output_asset": {
            "id": str(job.output_asset.pk),
            "name": job.output_asset.name,
            "filename": (job.output_asset.metadata or {}).get("original_name") or job.output_asset.name,
        } if job.output_asset_id else None,
        "message": job.message,
        "created_at": job.created_at.isoformat(),
        "updated_at": job.updated_at.isoformat(),
    }


def _uuid(value):
    try:
        return uuid.UUID(str(value))
    except (ValueError, TypeError, AttributeError):
        raise ValueError("Invalid record identifier.") from None


def _preset(data, key, max_length=200):
    value = data.get(key)
    if not isinstance(value, str) or not (1 <= len(value.strip()) <= max_length):
        raise ValueError(f"A valid {key.replace('_', ' ')} is required.")
    value = value.strip()
    if any(ord(char) < 32 or ord(char) == 127 for char in value):
        raise ValueError("Preset names cannot contain control characters.")
    # A label/reference only. Never forward this field as a path or CLI flag.
    if "/" in value or "\\" in value or value.startswith("-") or ".." in value:
        raise ValueError("Preset selections must be registered profile names, not paths or flags.")
    return value


def _draft_plate_settings(user, input_asset, settings):
    """Persist preview-only plate geometry; never compile it into slicer flags."""
    if settings in ({}, None):
        return {}
    if not isinstance(settings, dict) or set(settings) != {"plate_objects"}:
        raise ValueError("Unsupported slicer plate settings.")
    objects = settings["plate_objects"]
    if not isinstance(objects, list) or not 1 <= len(objects) <= 12:
        raise ValueError("The visual build plate supports one to twelve model instances.")
    seen = set()
    saved = []
    for item in objects:
        if not isinstance(item, dict) or set(item) != {
            "instance_id", "asset_id", "x_mm", "y_mm", "rotation_deg",
            "scale_percent", "color",
        }:
            raise ValueError("Invalid plate model instance.")
        instance_id = str(_uuid(item["instance_id"]))
        asset_id = _uuid(item["asset_id"])
        if instance_id in seen:
            raise ValueError("Plate instance IDs must be unique.")
        seen.add(instance_id)
        asset = FileAsset.objects.filter(pk=asset_id, owner=user, category="mesh").first()
        if not asset or not str((asset.metadata or {}).get("extension") or (asset.name or "")[-4:]).lower().endswith(".stl"):
            raise ValueError("Every plate model must be an owned STL asset.")
        values = {}
        for key, bound in (("x_mm", 10000), ("y_mm", 10000), ("rotation_deg", 360), ("scale_percent", 400)):
            raw = item[key]
            if isinstance(raw, bool) or not isinstance(raw, (int, float)) or not math.isfinite(raw):
                raise ValueError("Plate coordinates must be finite numbers.")
            if key == "scale_percent" and not 5 <= raw <= bound:
                raise ValueError("Plate scale must be between 5% and 400%.")
            if key != "scale_percent" and abs(raw) > bound:
                raise ValueError("Plate transform exceeds its allowed range.")
            values[key] = round(float(raw), 3)
        color = item["color"]
        if not isinstance(color, str) or not re.fullmatch(r"#[0-9a-fA-F]{6}", color):
            raise ValueError("Choose a six-digit colour for each model.")
        saved.append({"instance_id": instance_id, "asset_id": str(asset_id),
                      **values, "color": color.lower()})
    if saved[0]["asset_id"] != str(input_asset.pk):
        raise ValueError("The first plate model must match the selected primary STL.")
    return {"plate_objects": saved}


def _draft(user, data):
    if not isinstance(data, dict) or len(json.dumps(data)) > 8192:
        raise ValueError("Slice configuration must be a small JSON object.")
    allowed = {"engine", "engine_version", "input_asset_id", "printer_id", "spool_id", "printer_preset", "filament_preset", "process_preset", "nozzle_mm", "plate", "settings", "printer_profile_id", "filament_profile_id", "process_profile_id"}
    if set(data) - allowed:
        raise ValueError("Unknown slicing configuration fields.")
    engine = get_engine(data.get("engine"))
    version = _preset(data, "engine_version", 80)
    input_asset = FileAsset.objects.filter(pk=_uuid(data.get("input_asset_id")), owner=user).first()
    if not input_asset or input_asset.category not in {"mesh", "slicer"}:
        raise ValueError("Choose a model asset you own.")
    # Initial preparation accepts STL only; 3MF parsing requires a verified worker.
    metadata = input_asset.metadata or {}
    original_filename = str(metadata.get("original_name") or "")
    stored_filename = str(input_asset.file.name or "")
    suffix = str(metadata.get("extension") or "").lower()
    if not (
        suffix == ".stl"
        or original_filename.lower().endswith(".stl")
        or stored_filename.lower().endswith(".stl")
        or input_asset.name.lower().endswith(".stl")
    ):
        raise ValueError("The initial slicing workflow accepts STL input only.")
    printer = Printer.objects.filter(pk=_uuid(data.get("printer_id")), owner=user, is_active=True).first()
    if not printer:
        raise ValueError("Choose an active printer you own.")
    spool = None
    if data.get("spool_id"):
        spool = Spool.objects.filter(pk=_uuid(data.get("spool_id")), owner=user).first()
        if not spool:
            raise ValueError("Choose a spool you own.")
    try:
        nozzle = Decimal(str(data.get("nozzle_mm")))
    except (TypeError, ValueError, InvalidOperation):
        raise ValueError("Choose a valid nozzle diameter.") from None
    if not nozzle.is_finite() or not Decimal("0.10") <= nozzle <= Decimal("2.00") or nozzle.as_tuple().exponent < -2:
        raise ValueError("Nozzle diameter must be between 0.10 and 2.00 mm with at most two decimals.")
    settings_data = data.get("settings", {})
    settings_data = _draft_plate_settings(user, input_asset, settings_data)
    native_profiles = {}
    native_labels = {}
    for kind in ("printer", "filament", "process"):
        label = _preset(data, f"{kind}_preset")
        raw_id = data.get(f"{kind}_profile_id")
        profile = None
        if raw_id:
            profile = SlicerProfile.objects.filter(
                pk=_uuid(raw_id), owner=user, engine=engine.key,
                engine_version=version, kind=kind
            ).first()
            if not profile:
                raise ValueError(f"Selected {kind} native profile was not found for this engine/version.")
            if profile.name != label:
                raise ValueError(f"{kind.title()} preset must match the selected native profile.")
        native_profiles[f"{kind}_profile"] = profile
        native_labels[f"{kind}_preset"] = label

    return SliceJob.objects.create(
        owner=user, input_asset=input_asset, printer=printer, spool=spool,
        **native_profiles,
        engine=engine.key, engine_version=version,
        **native_labels,
        nozzle_mm=nozzle, plate=_preset(data, "plate", 80) if "plate" in data else "default",
        status="draft", settings=settings_data,
    )


@login_required
@require_http_methods(["GET"])
def inspect_mesh(request, asset_id):
    """Source-file dimensions only; never an implied build-plate compatibility check."""
    asset = FileAsset.objects.filter(
        pk=asset_id, owner=request.user, category="mesh"
    ).first()
    if not asset:
        return _error("STL model not found.", 404)
    metadata = asset.metadata or {}
    filename = str(metadata.get("original_name") or asset.name)
    if not (filename.lower().endswith(".stl") or
            str(metadata.get("extension") or "").lower() == ".stl"):
        return _error("Only STL models can be inspected.", 400)
    if not asset.file:
        return _error("Selected STL has no stored content.", 422)
    try:
        with asset.file.open("rb") as stream:
            raw = stream.read(MAX_INSPECTION_BYTES + 1)
        result = inspect_stl(raw)
    except (OSError, ValueError, MeshInspectionError):
        return _error("STL geometry could not be safely inspected.", 422)
    return JsonResponse({"file_asset_id": str(asset.pk), "mesh": result})


@login_required
@require_http_methods(["GET"])
def engines(request):
    installed = verified_installation()
    rows = engine_catalogue()
    for row in rows:
        if row["key"] in installed:
            row.update({"available": True, "enabled": True, "status": "validated"})
    return JsonResponse({
        "engines": rows,
        "worker_configured": bool(installed),
        # Deployment intent is distinct from a healthy, approved engine.
        # Never infer an installed container merely because code is present.
        "deployment_enabled": os.environ.get("MAKERVAULT_SLICER_EXECUTION_ENABLED") == "1",
        "preview_enabled": os.environ.get("MAKERVAULT_SLICER_PREVIEW_ENABLED") == "1" and request.user.is_superuser,
    })


@login_required
@require_http_methods(["GET", "POST"])
def jobs(request):
    if request.method == "GET":
        installed = verified_installation()
        return JsonResponse({
            "jobs": [serialise(job, installed) for job in _rows(request.user)[:100]],
            "worker_configured": bool(installed),
            "can_cancel": request.user.has_perm("core.change_slicejob"),
        })
    if not request.user.has_perm("core.add_fileasset"):
        return _error("You do not have permission to prepare slicing jobs.", 403)
    try:
        if len(request.body) > 8192:
            return _error("Slice configuration is too large.", 413)
        data = json.loads(request.body.decode("utf-8"))
        job = _draft(request.user, data)
    except (ValueError, TypeError, UnicodeDecodeError) as exc:
        return _error(str(exc) if isinstance(exc, ValueError) else "Invalid slice configuration.")
    return JsonResponse({"job": serialise(job), "execution_available": False}, status=201)


@login_required
@require_http_methods(["GET", "DELETE"])
def job_detail(request, job_id):
    job = _rows(request.user).filter(pk=job_id).first()
    if not job:
        return _error("Slice job not found.", 404)
    if request.method == "DELETE":
        if not request.user.has_perm("core.delete_slicejob"):
            return _error("You do not have permission to delete slicing drafts.", 403)
        if job.status != "draft":
            return _error("Only unscheduled slicing drafts can be deleted.", 409)
        job.delete()
        return JsonResponse({"deleted": True})
    installed = verified_installation()
    return JsonResponse({"job": serialise(job, installed), "execution_available": bool(installed)})


def _profile_summary(profile):
    return {
        "id": str(profile.pk), "engine": profile.engine,
        "engine_version": profile.engine_version, "kind": profile.kind,
        "name": profile.name, "status": profile.status,
        "file_asset_id": str(profile.file_asset_id),
        "content_sha256": profile.content_sha256,
        "provenance": profile.provenance,
    }


@login_required
@require_http_methods(["GET", "POST"])
def official_profiles(request):
    """Search/import only a fixed, tagged official source, never arbitrary URLs."""
    if request.method == "GET":
        try:
            results = search_official_profiles(
                request.GET.get("q", ""),
                request.GET.get("kind", "printer"),
                request.GET.get("vendor", "Creality"),
            )
        except OfficialProfileError as exc:
            return _error(str(exc), 503 if "source" in str(exc).lower() or "contact" in str(exc).lower() else 400)
        return JsonResponse(results)
    if not request.user.has_perm("core.add_fileasset"):
        return _error("You do not have permission to import official native profiles.", 403)
    if len(request.body) > 4096:
        return _error("Official profile selection is too large.", 413)
    try:
        selection = json.loads(request.body.decode("utf-8"))
        if not isinstance(selection, dict) or set(selection) - {"vendor", "kind", "name", "sub_path"}:
            raise ValueError("Invalid official profile selection.")
        kind = selection.get("kind")
        vendor = selection.get("vendor", "Creality")
        name = selection.get("name")
        subpath = selection.get("sub_path")
        if not isinstance(name, str) or len(name) > 200:
            raise ValueError("Invalid native profile name.")
        if SlicerProfile.objects.filter(
            owner=request.user, engine="orcaslicer",
            engine_version=OFFICIAL_ORCA_VERSION, kind=kind, name=name,
        ).exists():
            return _error("This exact official preset has already been imported.", 409)
        raw = fetch_official_profile(kind, name, subpath, vendor)
        asset = FileAsset(
            owner=request.user, name=name + ".json", category="source",
            metadata={"original_name": name + ".json", "extension": ".json"},
        )
        asset.file = ContentFile(raw, name="official-orca-profile.json")
        inspected = inspect_native_profile(asset, "orcaslicer")
        provenance = f"{OFFICIAL_ORCA_SOURCE}@{OFFICIAL_ORCA_REF}/{vendor}/{subpath}"
        if len(provenance) > 200:
            raise ValueError("Official source identity is too long.")
        with transaction.atomic():
            asset.save()
            profile = SlicerProfile.objects.create(
                owner=request.user, file_asset=asset, engine="orcaslicer",
                engine_version=OFFICIAL_ORCA_VERSION, kind=kind, name=name,
                provenance=provenance, content_sha256=inspected["sha256"], status="candidate",
            )
    except (OfficialProfileError, ValueError, TypeError, UnicodeDecodeError, SlicerProfileError) as exc:
        return _error(str(exc))
    except IntegrityError:
        return _error("The selected official profile is already registered.", 409)
    return JsonResponse({
        "profile": _profile_summary(profile), "engine_version": OFFICIAL_ORCA_VERSION,
        "execution_available": False,
        "warning": "Official origin does not imply runtime approval; profile inheritance may remain unresolved.",
    }, status=201)


@login_required
@require_http_methods(["GET", "POST"])
def profiles(request):
    if request.method == "GET":
        rows = SlicerProfile.objects.filter(owner=request.user).order_by(
            "engine", "kind", "name"
        )[:500]
        return JsonResponse({"profiles": [_profile_summary(row) for row in rows]})

    if not request.user.has_perm("core.add_fileasset"):
        return _error("You do not have permission to import slicing profiles.", 403)
    try:
        if len(request.body) > 4096:
            return _error("Profile registration is too large.", 413)
        data = json.loads(request.body.decode("utf-8"))
        if not isinstance(data, dict) or set(data) - {
            "file_asset_id", "engine", "engine_version", "kind", "name", "provenance"
        }:
            raise ValueError("Invalid native profile registration fields.")
        engine = get_engine(data.get("engine"))
        version = _preset(data, "engine_version", 80)
        kind = data.get("kind")
        if kind not in dict(SlicerProfile.KINDS):
            raise ValueError("Select a printer, filament or process profile.")
        name = _preset(data, "name")
        asset = FileAsset.objects.filter(
            pk=_uuid(data.get("file_asset_id")), owner=request.user
        ).first()
        if not asset:
            raise ValueError("Select a profile file you own.")
        provenance = str(data.get("provenance") or "").strip()
        if len(provenance) > 200 or any(ord(char) < 32 for char in provenance):
            raise ValueError("Invalid profile source label.")
        inspected = inspect_native_profile(asset, engine.key)
        with transaction.atomic():
            profile = SlicerProfile.objects.create(
                owner=request.user, file_asset=asset, engine=engine.key,
                engine_version=version, kind=kind, name=name,
                provenance=provenance, content_sha256=inspected["sha256"],
                status="candidate",
            )
    except (ValueError, TypeError, UnicodeDecodeError, SlicerProfileError) as exc:
        return _error(str(exc))
    except IntegrityError:
        return _error("A profile with this engine, version, kind and name already exists.", 409)
    return JsonResponse({"profile": _profile_summary(profile), "execution_available": False}, status=201)


@login_required
@require_http_methods(["GET"])
def profile_plate(request, profile_id):
    profile = SlicerProfile.objects.filter(
        pk=profile_id, owner=request.user, engine="orcaslicer", kind="printer"
    ).select_related("file_asset").first()
    if not profile:
        return _error("Native Orca machine profile not found.", 404)
    try:
        geometry = inspect_orca_plate(profile)
    except SlicerProfileError:
        return _error("Native printer geometry could not be safely inspected.", 422)
    return JsonResponse({"profile_id": str(profile.pk), "plate": geometry})


@login_required
@require_http_methods(["GET"])
def profile_dependencies(request, profile_id):
    """Inspect only the current user's exact Orca engine/version/kind profiles."""
    profile = SlicerProfile.objects.filter(
        pk=profile_id, owner=request.user
    ).select_related("file_asset").first()
    if not profile:
        return _error("Native profile not found.", 404)
    if profile.engine != "orcaslicer":
        return _error("Dependency inspection currently supports OrcaSlicer only.", 409)
    candidates = list(SlicerProfile.objects.filter(
        owner=request.user, engine=profile.engine,
        engine_version=profile.engine_version, kind=profile.kind
    ).select_related("file_asset")[:500])
    try:
        result = inspect_orca_lineage(profile, candidates)
    except SlicerProfileError:
        return _error("Native profile dependency inspection failed.", 422)
    return JsonResponse({"profile_id": str(profile.pk), "lineage": result})


@login_required
@require_http_methods(["POST"])
def job_cancel(request, job_id):
    """Cancel drafts or queued jobs without terminating an in-flight worker.

    The Celery task can only claim a queued row. Running jobs require a
    separate authenticated worker cancellation protocol before cancellation
    is offered; silently marking those cancelled could leave execution live.
    """
    from django.db import transaction
    with transaction.atomic():
        job = SliceJob.objects.select_for_update(of=("self",)).filter(
            pk=job_id, owner=request.user,
        ).first()
        if not job:
            return _error("Slice job not found.", 404)
        if job.status not in {"draft", "queued"}:
            return _error("Only drafts and jobs awaiting a worker can be cancelled.", 409)
        if not request.user.has_perm("core.change_slicejob"):
            return _error("You do not have permission to cancel slicing jobs.", 403)
        job.status = "cancelled"
        job.message = "Cancelled before slicing started."
        job.save(update_fields=["status", "message", "updated_at"])
    return JsonResponse({"job": serialise(job), "cancelled": True})


@login_required
@require_http_methods(["POST"])
def job_start(request, job_id):
    """A separate explicit slice action; never submits to any printer."""
    if not request.user.has_perm("core.add_fileasset"):
        return _error("You do not have permission to start slicing.", 403)
    try:
        job = queue_draft(job_id, request.user)
    except (SlicerExecutionError, ValueError) as exc:
        return _error(str(exc), 409)
    return JsonResponse({"job": serialise(job), "queued": True}, status=202)
