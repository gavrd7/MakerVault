"""Explicitly gated queue/execution lifecycle for one isolated engine.

Nothing in this module starts a printer, changes spool stock or installs engines.
All execution is blocked unless an administrator configures a digest-pinned
and verified worker and explicitly approves all three engine-native profiles.
"""
import hashlib
import os
from django.db import transaction
from django.utils import timezone

from .models import SliceJob
from .slicer_engines import validate_engine_selection
from .slicer_output import store_generated_gcode
from .slicer_worker_client import SlicerWorkerError, health, run_remote_job


MAX_INPUT = 32 * 1024 * 1024
MAX_PROFILE = 1024 * 1024


class SlicerExecutionError(ValueError):
    pass


def verified_installation():
    """Fail closed: explicit deployment approval plus worker health is required."""
    if os.environ.get("MAKERVAULT_SLICER_EXECUTION_ENABLED") != "1":
        return {}
    digest = os.environ.get("MAKERVAULT_SLICER_ENGINE_IMAGE_DIGEST", "")
    version = os.environ.get("MAKERVAULT_SLICER_PRUSA_VERSION", "")
    if not digest or not version:
        return {}
    try:
        worker = health()
        if not worker["ready"] or worker["engine"] != "prusaslicer" or worker["version"] != version:
            return {}
        validate_engine_selection("prusaslicer", version, {
            "prusaslicer": {
                "version": version, "enabled": True, "verified": True,
                "image_digest": digest,
            }
        })
    except (ValueError, SlicerWorkerError):
        return {}
    return {"prusaslicer": {
        "version": version, "enabled": True, "verified": True,
        "image_digest": digest,
    }}


def validate_scheduling(job, installed=None):
    """Pure admission check; caller must hold a row lock before queueing."""
    if job.status != "draft" or job.output_asset_id:
        raise SlicerExecutionError("Only unscheduled slice drafts can be queued.")
    if not installed:
        raise SlicerExecutionError("No administrator-verified slicing worker is enabled.")
    validate_engine_selection(job.engine, job.engine_version, installed)
    if not job.printer.is_active or job.printer.owner_id != job.owner_id:
        raise SlicerExecutionError("Selected printer is inactive or unavailable.")
    if job.input_asset.owner_id != job.owner_id or job.input_asset.category != "mesh":
        raise SlicerExecutionError("Input model no longer belongs to this job.")
    for kind in ("printer", "filament", "process"):
        profile = getattr(job, f"{kind}_profile", None)
        if not profile or profile.status != "verified":
            raise SlicerExecutionError("All three native profiles require administrator verification.")
        if (
            profile.owner_id != job.owner_id or profile.engine != job.engine
            or profile.engine_version != job.engine_version or profile.kind != kind
            or profile.name != getattr(job, f"{kind}_preset")
        ):
            raise SlicerExecutionError("Slicing profile identity changed; prepare a new draft.")
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
        with asset.file.open("rb") as stream:
            data = stream.read(maximum + 1)
    except (OSError, ValueError):
        raise SlicerExecutionError(f"{label} file cannot be read.") from None
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
    try:
        model = _read_owned_file(job.input_asset, job.owner_id, MAX_INPUT, "Model")
        profiles = []
        for kind in ("printer", "filament", "process"):
            profile = getattr(job, f"{kind}_profile")
            data = _read_owned_file(profile.file_asset, job.owner_id, MAX_PROFILE, "Native profile")
            if hashlib.sha256(data).hexdigest() != profile.content_sha256:
                raise SlicerExecutionError("Native profile contents changed since verification.")
            profiles.append(data)
        if job.input_asset.sha256 and hashlib.sha256(model).hexdigest() != job.input_asset.sha256:
            raise SlicerExecutionError("Model contents changed since the job was prepared.")
        output = run_remote_job(
            job.pk, job.engine, job.engine_version, model,
            profiles[0], profiles[1], profiles[2],
        )
        asset = store_generated_gcode(job.pk, output)
        return {"status": "completed", "asset_id": str(asset.pk)}
    except Exception:
        with transaction.atomic():
            row = SliceJob.objects.select_for_update().filter(pk=job.pk).first()
            if row and row.status == "running":
                row.status = "failed"
                row.message = "Slicing failed or worker response could not be verified."
                row.save(update_fields=["status", "message", "updated_at"])
        return {"status": "failed"}


def validate_scheduling_for_worker(job, installed):
    """Recheck immediately before entering running state; no separate queueing."""
    if job.status != "queued":
        raise SlicerExecutionError("Job is not queued.")
    if not installed:
        raise SlicerExecutionError("Isolated slicing worker is no longer approved.")
    validate_engine_selection(job.engine, job.engine_version, installed)
    if job.printer.owner_id != job.owner_id or job.input_asset.owner_id != job.owner_id:
        raise SlicerExecutionError("Job ownership changed.")
    for kind in ("printer", "filament", "process"):
        profile = getattr(job, f"{kind}_profile")
        if (
            not profile or profile.status != "verified" or profile.owner_id != job.owner_id
            or profile.engine != job.engine or profile.engine_version != job.engine_version
            or profile.kind != kind or profile.name != getattr(job, f"{kind}_preset")
        ):
            raise SlicerExecutionError("Native slicer profiles are no longer verified.")
