"""Owner-scoped slicer drafts and engine discovery; no execution endpoints yet."""
import json
import uuid
from decimal import Decimal, InvalidOperation

from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.db import IntegrityError, transaction
from django.views.decorators.http import require_http_methods

from .models import FileAsset, Printer, SliceJob, Spool, SlicerProfile
from .slicer_engines import engine_catalogue, get_engine
from .slicer_profiles import SlicerProfileError, inspect_native_profile


def _error(message, status=400):
    return JsonResponse({"error": message}, status=status)


def _rows(user):
    return SliceJob.objects.filter(owner=user).select_related(
        "input_asset", "printer", "spool", "output_asset"
    )


def serialise(job):
    return {
        "id": str(job.id),
        "status": job.status,
        "progress": job.progress,
        "engine": job.engine,
        "engine_version": job.engine_version,
        "printer_preset": job.printer_preset,
        "filament_preset": job.filament_preset,
        "process_preset": job.process_preset,
        "nozzle_mm": str(job.nozzle_mm),
        "plate": job.plate,
        "settings": job.settings,
        "input_asset": {"id": str(job.input_asset_id), "name": job.input_asset.name},
        "printer": {"id": str(job.printer_id), "name": job.printer.name},
        "spool": {"id": str(job.spool_id), "name": job.spool.spool_id} if job.spool_id else None,
        "output_asset_id": str(job.output_asset_id) if job.output_asset_id else None,
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


def _draft(user, data):
    if not isinstance(data, dict) or len(json.dumps(data)) > 8192:
        raise ValueError("Slice configuration must be a small JSON object.")
    allowed = {"engine", "engine_version", "input_asset_id", "printer_id", "spool_id", "printer_preset", "filament_preset", "process_preset", "nozzle_mm", "plate", "settings"}
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
    if not isinstance(settings_data, dict) or settings_data:
        # Each engine setting requires a typed schema before it is accepted.
        raise ValueError("Custom settings are unavailable until engine profiles are validated.")
    return SliceJob.objects.create(
        owner=user, input_asset=input_asset, printer=printer, spool=spool,
        engine=engine.key, engine_version=version,
        printer_preset=_preset(data, "printer_preset"),
        filament_preset=_preset(data, "filament_preset"),
        process_preset=_preset(data, "process_preset"),
        nozzle_mm=nozzle, plate=_preset(data, "plate", 80) if "plate" in data else "default",
        status="draft", settings={},
    )


@login_required
@require_http_methods(["GET"])
def engines(request):
    return JsonResponse({"engines": engine_catalogue(), "worker_configured": False})


@login_required
@require_http_methods(["GET", "POST"])
def jobs(request):
    if request.method == "GET":
        return JsonResponse({"jobs": [serialise(job) for job in _rows(request.user)[:100]]})
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
    return JsonResponse({"job": serialise(job), "execution_available": False})


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
