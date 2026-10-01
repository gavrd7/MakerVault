from __future__ import annotations

import math

from django.utils import timezone

from .models import PrintJob


TERMINAL_STATES = {
    "complete": "success",
    "completed": "success",
    "success": "success",
    "cancelled": "cancelled",
    "canceled": "cancelled",
    "error": "failed",
    "failed": "failed",
}


def _live_meta(job) -> dict:
    settings = job.settings or {}
    value = settings.get("live_monitor") or {}
    return value if isinstance(value, dict) else {}


def _active_live_job(connection):
    rows = PrintJob.objects.filter(
        owner=connection.printer.owner,
        printer=connection.printer,
        status="printing",
    ).order_by("-created_at")
    for job in rows:
        if _live_meta(job).get("source") == "live_printer":
            return job
    return None


def _minutes(seconds):
    try:
        value = float(seconds)
    except (TypeError, ValueError):
        return None
    if value < 0:
        return None
    return max(1, int(math.ceil(value / 60.0))) if value else 0


def _merge_source(meta: dict, connection) -> dict:
    sources = meta.get("sources")
    if not isinstance(sources, list):
        sources = []
    identity = {
        "connection_id": str(connection.id),
        "adapter": connection.adapter,
    }
    if identity not in sources:
        sources.append(identity)
    meta["sources"] = sources
    return meta


def sync_print_job_from_snapshot(connection, snapshot: dict) -> dict:
    """Conservatively map high-confidence live activity onto MakerVault PrintJob.

    A job is created automatically only after a live adapter reports printing
    with a non-empty filename. Multiple adapters attached to the same physical
    printer converge on the same active monitored job rather than creating
    duplicates. Idle/offline transitions never imply success.
    """
    state = str(snapshot.get("state") or "").strip().lower()
    job_data = snapshot.get("job") or {}
    filename = str(job_data.get("file_name") or "").strip()
    elapsed = job_data.get("elapsed_seconds")
    remaining = job_data.get("remaining_seconds")
    progress = job_data.get("progress")
    now = timezone.now()

    active = _active_live_job(connection)

    if state == "printing":
        if active is None:
            if not filename:
                return {"action": "none", "reason": "missing-filename"}
            meta = {
                "source": "live_printer",
                "filename": filename,
                "first_observed_at": now.isoformat(),
                "last_observed_at": now.isoformat(),
                "last_state": state,
                "last_progress": progress,
            }
            meta = _merge_source(meta, connection)
            estimated = None
            if elapsed is not None and remaining is not None:
                estimated = _minutes(float(elapsed) + float(remaining))
            active = PrintJob.objects.create(
                owner=connection.printer.owner,
                printer=connection.printer,
                status="printing",
                quantity=1,
                estimated_minutes=estimated,
                settings={"live_monitor": meta},
            )
            return {
                "action": "created",
                "job_id": str(active.id),
                "status": active.status,
            }

        meta = dict(_live_meta(active))
        known_filename = str(meta.get("filename") or "").strip()
        if known_filename and filename and known_filename != filename:
            return {
                "action": "none",
                "reason": "active-job-filename-mismatch",
                "job_id": str(active.id),
            }
        if filename and not known_filename:
            meta["filename"] = filename
        meta["last_observed_at"] = now.isoformat()
        meta["last_state"] = state
        meta["last_progress"] = progress
        meta = _merge_source(meta, connection)
        settings = dict(active.settings or {})
        settings["live_monitor"] = meta
        active.settings = settings
        if elapsed is not None and remaining is not None:
            active.estimated_minutes = _minutes(float(elapsed) + float(remaining))
        active.save(update_fields=["settings", "estimated_minutes", "updated_at"])
        return {
            "action": "updated",
            "job_id": str(active.id),
            "status": active.status,
        }

    if active and state in TERMINAL_STATES:
        meta = dict(_live_meta(active))
        known_filename = str(meta.get("filename") or "").strip()
        if known_filename and filename and known_filename != filename:
            return {
                "action": "none",
                "reason": "terminal-filename-mismatch",
                "job_id": str(active.id),
            }
        meta["last_observed_at"] = now.isoformat()
        meta["finished_observed_at"] = now.isoformat()
        meta["last_state"] = state
        meta["last_progress"] = progress
        meta = _merge_source(meta, connection)
        settings = dict(active.settings or {})
        settings["live_monitor"] = meta
        active.settings = settings
        active.status = TERMINAL_STATES[state]
        actual = _minutes(elapsed)
        if actual is not None:
            active.actual_minutes = actual
        active.save(update_fields=["settings", "status", "actual_minutes", "updated_at"])
        return {
            "action": "completed",
            "job_id": str(active.id),
            "status": active.status,
        }

    if active and state in {"paused", "pause"}:
        meta = dict(_live_meta(active))
        meta["last_observed_at"] = now.isoformat()
        meta["last_state"] = "paused"
        meta["last_progress"] = progress
        meta = _merge_source(meta, connection)
        settings = dict(active.settings or {})
        settings["live_monitor"] = meta
        active.settings = settings
        active.save(update_fields=["settings", "updated_at"])
        return {
            "action": "updated",
            "job_id": str(active.id),
            "status": active.status,
        }

    return {"action": "none", "reason": "no-confident-transition"}
