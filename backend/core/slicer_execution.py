"""Explicitly gated queue/execution lifecycle for one isolated engine.

Nothing in this module starts a printer, changes spool stock or installs engines.
All execution is blocked unless an administrator configures a digest-pinned
and verified worker and explicitly approves all three engine-native profiles.
"""
import hashlib
import os
from datetime import timedelta
from django.db import transaction
from django.utils import timezone

from .models import SliceJob
from .slicer_engines import validate_engine_selection
from .slicer_output import store_generated_gcode
from .slicer_native_resolution import resolved_native_profile
from .slicer_worker_client import SlicerWorkerError, health, run_remote_job


MAX_INPUT = 32 * 1024 * 1024
MAX_PROFILE = 1024 * 1024


class SlicerExecutionError(ValueError):
    pass


def verified_installation():
    """Fail closed for each independently approved engine in the shared worker.

    Legacy single-engine settings remain supported. Multi-engine approval requires
    a pinned common image and a JSON map of exact versions and binary hashes.
    The API only reports an engine available when that exact entry is healthy.
    """
    if os.environ.get("MAKERVAULT_SLICER_EXECUTION_ENABLED") != "1":
        return {}
    digest = os.environ.get("MAKERVAULT_SLICER_ENGINE_IMAGE_DIGEST", "")
    image_ref = os.environ.get("MAKERVAULT_SLICER_WORKER_IMAGE", "")
    if (
        not digest.startswith("sha256:") or len(digest) != 71
        or any(c not in "0123456789abcdef" for c in digest[7:])
        or not image_ref.endswith("@" + digest)
        or image_ref.count("@") != 1
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


def _check_profile_evidence(profile, installation):
    evidence = profile.verification_evidence or {}
    if (
        evidence.get("engine_version") != installation["version"]
        or evidence.get("image_digest") != installation["image_digest"]
        or evidence.get("engine_binary_sha256") != installation.get("binary_sha256")
        or not isinstance(evidence.get("receipt_sha256"), str)
        or len(evidence["receipt_sha256"]) != 64
        or not isinstance(evidence.get("gcode_sha256"), str)
        or len(evidence["gcode_sha256"]) != 64
    ):
        raise SlicerExecutionError("Native profile approval no longer matches this pinned worker.")


def _plate_is_single_unmodified_source(job):
    """Single STL at original transform needs no worker-side 3MF construction."""
    objects = (job.settings or {}).get("plate_objects")
    if not objects:
        return True
    if not isinstance(objects, list) or len(objects) != 1:
        return False
    model = objects[0]
    if str(model.get("asset_id")) != str(job.input_asset_id):
        return False
    return (
        model.get("x_mm") == 0 and model.get("y_mm") == 0
        and model.get("rotation_deg") == 0
        and model.get("scale_percent") == 100
    )


def validate_scheduling(job, installed=None):
    """Pure admission check; caller must hold a row lock before queueing."""
    if not _plate_is_single_unmodified_source(job):
        raise SlicerExecutionError("Transformed or multi-object plates require the verified 3MF worker path.")
    if job.status != "draft" or job.output_asset_id:
        raise SlicerExecutionError("Only unscheduled slice drafts can be queued.")
    if not installed:
        raise SlicerExecutionError("No administrator-verified slicing worker is enabled.")
    installation = validate_engine_selection(job.engine, job.engine_version, installed)
    installation["binary_sha256"] = installed[job.engine].get("binary_sha256")
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
        _check_profile_evidence(profile, installation)
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
            profiles.append(resolved_native_profile(profile)
                            if job.engine in {"orcaslicer", "crealityprint"} else data)
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
    installation = validate_engine_selection(job.engine, job.engine_version, installed)
    installation["binary_sha256"] = installed[job.engine].get("binary_sha256")
    if not _plate_is_single_unmodified_source(job):
        raise SlicerExecutionError("Transformed or multi-object plates cannot run in the single-STL worker.")
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
        _check_profile_evidence(profile, installation)


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
