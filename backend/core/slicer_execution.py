"""Explicitly gated queue/execution lifecycle for one isolated engine.

Nothing in this module starts a printer, changes spool stock or installs engines.
Execution requires a digest-pinned, healthy isolated worker and owner-scoped
native profiles with validated content and intact inheritance chains.
"""
import hashlib
import logging
import os
from datetime import timedelta
from django.db import transaction
from django.utils import timezone

from .models import SliceJob, FileAsset
from .slicer_engines import validate_engine_selection
from .slicer_output import store_generated_gcode
from .slicer_native_resolution import resolved_native_profile
from .slicer_bed_dimensions import trusted_plate_dimensions
from .slicer_plate_3mf import build_plate_3mf, build_compound_plate_3mf
from .slicer_worker_client import SlicerWorkerError, health, run_remote_job


logger = logging.getLogger(__name__)

MAX_INPUT = 32 * 1024 * 1024
MAX_PROFILE = 1024 * 1024


class SlicerExecutionError(ValueError):
    pass


def verified_installation():
    """Fail closed for each independently approved engine in the shared worker.

    Legacy single-engine settings remain supported. Multi-engine approval requires
    a pinned image reference (registry digest or local image ID) and exact hashes.
    The API only reports an engine available when that exact entry is healthy.
    """
    if os.environ.get("MAKERVAULT_SLICER_EXECUTION_ENABLED") != "1":
        return {}
    digest = os.environ.get("MAKERVAULT_SLICER_ENGINE_IMAGE_DIGEST", "")
    image_ref = os.environ.get("MAKERVAULT_SLICER_WORKER_IMAGE", "")
    if (
        not digest.startswith("sha256:") or len(digest) != 71
        or any(c not in "0123456789abcdef" for c in digest[7:])
        or not (image_ref == digest or
                (image_ref.endswith("@" + digest) and image_ref.count("@") == 1))
    ):
        return {}
    configured = os.environ.get("MAKERVAULT_SLICER_ENGINES_JSON", "")
    if configured:
        try:
            import json
            approvals = json.loads(configured)
        except (ValueError, TypeError):
            return {}
        if not isinstance(approvals, dict) or not approvals or len(approvals) > 3:
            return {}
    else:
        approvals = {os.environ.get("MAKERVAULT_SLICER_ENGINE", "orcaslicer"): {
            "version": os.environ.get("MAKERVAULT_SLICER_ENGINE_VERSION", ""),
            "binary_sha256": os.environ.get("MAKERVAULT_SLICER_ENGINE_BINARY_SHA256", ""),
        }}
    try:
        worker = health()
    except (ValueError, SlicerWorkerError):
        return {}
    if not worker.get("ready"):
        return {}
    health_engines = worker.get("engines") or {}
    # Compatible with the original single-engine health response.
    if not health_engines and worker.get("engine") and worker.get("version"):
        health_engines = {worker["engine"]: {
            "version": worker["version"],
            "binary_sha256": worker.get("binary_sha256"),
            "ready": True,
        }}
    installed = {}
    for engine, entry in approvals.items():
        if not isinstance(entry, dict) or set(entry) != {"version", "binary_sha256"}:
            continue
        version, checksum = entry["version"], entry["binary_sha256"]
        if (not isinstance(version, str) or not 1 <= len(version) <= 80
                or not isinstance(checksum, str) or len(checksum) != 64
                or any(c not in "0123456789abcdef" for c in checksum)):
            continue
        worker_entry = health_engines.get(engine)
        if (not isinstance(worker_entry, dict) or worker_entry.get("ready") is not True
                or worker_entry.get("version") != version
                or worker_entry.get("binary_sha256") != checksum):
            continue
        candidate = {engine: {
            "version": version, "enabled": True, "verified": True,
            "image_digest": digest, "binary_sha256": checksum,
        }}
        try:
            validate_engine_selection(engine, version, candidate)
        except ValueError:
            continue
        installed.update(candidate)
    return installed


def _check_profile_integrity(profile, job, kind):
    """Native profiles need no manual administrator approval.

    Refuse changed, missing or unsupported profile data at queue admission,
    while preserving the pinned worker and explicit user-selected identity.
    """
    from .slicer_profiles import inspect_native_profile, SlicerProfileError
    from .slicer_native_resolution import resolved_native_profile
    if (not profile or profile.owner_id != job.owner_id
            or profile.engine != job.engine or profile.engine_version != job.engine_version
            or profile.kind != kind or profile.name != getattr(job, f"{kind}_preset")):
        raise SlicerExecutionError("Selected native profiles no longer match this slicing job.")
    try:
        inspection = inspect_native_profile(profile.file_asset, profile.engine)
        if inspection["sha256"] != profile.content_sha256:
            raise SlicerExecutionError("Native profile contents changed after import.")
        if profile.engine in {"orcaslicer", "crealityprint"}:
            resolved_native_profile(profile)
    except (SlicerProfileError, ValueError, OSError) as exc:
        raise SlicerExecutionError("Native profile is invalid or its parent presets are incomplete: " +
                                   str(exc)) from exc


def _validate_plate_execution(job):
    """An untouched STL or a bounded native-bed-backed multi-object 3MF plate."""
    objects = (job.settings or {}).get("plate_objects")
    if not objects:
        return True
    if job.engine != "orcaslicer":
        raise SlicerExecutionError("Multi-model plate execution is currently verified only for the single-material OrcaSlicer worker.")
    if not isinstance(objects, list) or not 1 <= len(objects) <= 12:
        raise SlicerExecutionError("Plate model list is invalid.")
    if not job.printer_profile_id:
        raise SlicerExecutionError("Select a native printer profile for the 3MF plate.")
    try:
        trusted_plate_dimensions(job.printer_profile)
    except ValueError as exc:
        raise SlicerExecutionError("3MF plate requires supported native rectangular build dimensions.") from exc
    return True


def validate_scheduling(job, installed=None):
    """Pure admission check; caller must hold a row lock before queueing."""
    _validate_plate_execution(job)
    if job.status != "draft" or job.output_asset_id:
        raise SlicerExecutionError("Only unscheduled slice drafts can be queued.")
    if not installed:
        raise SlicerExecutionError("No verified isolated slicing worker is enabled.")
    installation = validate_engine_selection(job.engine, job.engine_version, installed)
    installation["binary_sha256"] = installed[job.engine].get("binary_sha256")
    if not job.printer.is_active or job.printer.owner_id != job.owner_id:
        raise SlicerExecutionError("Selected printer is inactive or unavailable.")
    if job.input_asset.owner_id != job.owner_id or job.input_asset.category != "mesh":
        raise SlicerExecutionError("Input model no longer belongs to this job.")
    for kind in ("printer", "filament", "process"):
        profile = getattr(job, f"{kind}_profile", None)
        _check_profile_integrity(profile, job, kind)
    return True


def queue_draft(job_id, user):
    installed = verified_installation()
    with transaction.atomic():
        job = SliceJob.objects.select_for_update(of=("self",)).select_related(
            "owner", "printer", "input_asset",
            "printer_profile", "filament_profile", "process_profile",
        ).filter(pk=job_id, owner=user).first()
        if not job:
            raise SlicerExecutionError("Slice draft not found.")
        validate_scheduling(job, installed)
        job.status = "queued"
        job.progress = 0
        job.message = "Queued for the isolated slicing worker."
        job.save(update_fields=["status", "progress", "message", "updated_at"])
    try:
        from .tasks import execute_slice_job_task
        execute_slice_job_task.delay(str(job.pk))
    except Exception:
        # If the broker fails, never leave an orphaned queued draft.
        with transaction.atomic():
            row = SliceJob.objects.select_for_update().get(pk=job.pk)
            if row.status == "queued":
                row.status = "draft"
                row.message = "Worker queue is unavailable; no slice was started."
                row.save(update_fields=["status", "message", "updated_at"])
        raise SlicerExecutionError("Slicing queue is unavailable.") from None
    return job


def _read_owned_file(asset, owner_id, maximum, label):
    if asset.owner_id != owner_id or not asset.file:
        raise SlicerExecutionError(f"{label} file is unavailable.")
    try:
        # Open through storage, not FieldFile.open(): the encrypted backend
        # decrypts into a temporary File which FieldFile can cache after close.
        # Reopening that cached File may attempt a filesystem path rather than
        # decrypting the private object afresh.
        with asset.file.storage.open(asset.file.name, "rb") as stream:
            data = stream.read(maximum + 1)
    except (OSError, ValueError) as exc:
        logger.warning("Slicer source read failed (%s, asset=%s): %s: %s",
                       label, asset.pk, type(exc).__name__, exc)
        raise SlicerExecutionError(f"{label} file cannot be read.") from exc
    if not data or len(data) > maximum:
        raise SlicerExecutionError(f"{label} exceeds the size limit.")
    return data


def process_queued_job(job_id):
    """At most one active run; worker loss becomes a failed, never resent job."""
    installed = verified_installation()
    with transaction.atomic():
        job = SliceJob.objects.select_for_update(of=("self",)).select_related(
            "owner", "input_asset", "printer",
            "printer_profile", "filament_profile", "process_profile",
        ).filter(pk=job_id).first()
        if not job or job.status != "queued":
            return {"status": "skipped"}
        try:
            validate_scheduling_for_worker(job, installed)
        except (SlicerExecutionError, ValueError):
            job.status = "failed"
            job.message = "The verified worker or native profiles are no longer available."
            job.save(update_fields=["status", "message", "updated_at"])
            return {"status": "failed"}
        job.status = "running"
        job.progress = 5
        job.message = "Preparing isolated slicing input."
        job.save(update_fields=["status", "progress", "message", "updated_at"])
    stage = "reading the source STL"
    try:
        model = _read_owned_file(job.input_asset, job.owner_id, MAX_INPUT, "Model")
        model_format = "stl"
        plate = (job.settings or {}).get("plate_objects")
        if plate:
            # Every source remains owner-scoped and verified at execution time;
            # arbitrary file paths and external 3MF projects are never accepted.
            source_models = []
            for item in plate:
                asset = FileAsset.objects.filter(
                    pk=item["asset_id"], owner_id=job.owner_id, category="mesh",
                ).first()
                if not asset:
                    raise SlicerExecutionError("A source STL is no longer available.")
                raw = _read_owned_file(asset, job.owner_id, MAX_INPUT, "Plate STL")
                if asset.sha256 and hashlib.sha256(raw).hexdigest() != asset.sha256:
                    raise SlicerExecutionError("A plate STL has changed since import.")
                source_models.append((item, raw))
            stage = "resolving native printer bed dimensions"
            width, depth = trusted_plate_dimensions(job.printer_profile)
            stage = "assembling the build plate 3MF"
            model = build_compound_plate_3mf(source_models, bed_width=width, bed_depth=depth)
            model_format = "3mf"
        stage = "resolving native slicing profiles"
        profiles = []
        for kind in ("printer", "filament", "process"):
            stage = "resolving native " + kind + " profile"
            profile = getattr(job, f"{kind}_profile")
            data = _read_owned_file(profile.file_asset, job.owner_id, MAX_PROFILE, "Native profile")
            if hashlib.sha256(data).hexdigest() != profile.content_sha256:
                raise SlicerExecutionError("Native profile contents changed since verification.")
            profiles.append(resolved_native_profile(profile)
                            if job.engine in {"orcaslicer", "crealityprint"} else data)
        if model_format == "stl" and job.input_asset.sha256 and hashlib.sha256(model).hexdigest() != job.input_asset.sha256:
            raise SlicerExecutionError("Model contents changed since the job was prepared.")
        stage = "executing the isolated slicer worker"
        output = run_remote_job(
            job.pk, job.engine, job.engine_version, model,
            profiles[0], profiles[1], profiles[2],
            model_format=model_format,
        )
        stage = "validating and storing generated G-code"
        asset = store_generated_gcode(job.pk, output)
        return {"status": "completed", "asset_id": str(asset.pk)}
    except Exception:
        # Preserve detailed traceback in server logs without exposing raw
        # profile contents, filesystem paths, tokens or worker responses to UI.
        logger.exception("Slicing job %s failed during %s", job.pk, stage)
        with transaction.atomic():
            row = SliceJob.objects.select_for_update().filter(pk=job.pk).first()
            if row and row.status == "running":
                row.status = "failed"
                row.message = "Slicing failed during " + stage + ". Check MakerVault worker logs for this job."
                row.save(update_fields=["status", "message", "updated_at"])
        return {"status": "failed"}


def validate_scheduling_for_worker(job, installed):
    """Recheck immediately before entering running state; no separate queueing."""
    if job.status != "queued":
        raise SlicerExecutionError("Job is not queued.")
    if not installed:
        raise SlicerExecutionError("Isolated slicing worker is no longer approved.")
    installation = validate_engine_selection(job.engine, job.engine_version, installed)
    installation["binary_sha256"] = installed[job.engine].get("binary_sha256")
    _validate_plate_execution(job)
    if job.printer.owner_id != job.owner_id or job.input_asset.owner_id != job.owner_id:
        raise SlicerExecutionError("Job ownership changed.")
    for kind in ("printer", "filament", "process"):
        profile = getattr(job, f"{kind}_profile")
        _check_profile_integrity(profile, job, kind)


def reconcile_stale_jobs(*, now=None, limit=250):
    """Mark abandoned queued/running jobs stale, never redispatch them.

    For a running worker that later finishes, output storage rejects any job
    already marked stale. This avoids duplicate slicing and ghost output.
    Run through the optional admin command or a future supervised scheduler.
    """
    now = now or timezone.now()
    if not isinstance(limit, int) or not 1 <= limit <= 1000:
        raise SlicerExecutionError("Invalid stale-job reconciliation limit.")
    thresholds = (
        ("queued", now - timedelta(minutes=30)),
        ("running", now - timedelta(minutes=25)),
    )
    counts = {}
    with transaction.atomic():
        for status, cutoff in thresholds:
            ids = list(
                SliceJob.objects.filter(status=status, updated_at__lt=cutoff)
                .order_by("updated_at").values_list("pk", flat=True)[:limit]
            )
            updated = SliceJob.objects.filter(
                pk__in=ids, status=status, updated_at__lt=cutoff
            ).update(
                status="stale",
                message="Worker outcome is unknown. Review and create a new draft if required.",
                updated_at=now,
            ) if ids else 0
            counts[status] = updated
    return counts
