"""Owner-scoped, explicitly confirmed bulk slicer-history and private-output cleanup.

This module never acts on printer submissions. G-code saved in the library
(category='gcode') and original STL/model sources remain untouched.
"""
import logging
import uuid

from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.db.models.deletion import ProtectedError
from django.http import JsonResponse
from django.views.decorators.http import require_POST

from .models import FileAsset, SliceJob

LOG = logging.getLogger(__name__)
INACTIVE = frozenset({"draft", "failed", "cancelled", "stale", "completed"})
MAX_SELECTED = 200
MAX_BULK = 5000


def _error(message, status=400):
    return JsonResponse({"error": message}, status=status)


def _payload(request, permitted):
    import json
    if len(request.body) > 16384:
        raise ValueError("Bulk selection exceeds the request limit.")
    value = json.loads(request.body.decode("utf-8"))
    if not isinstance(value, dict) or set(value) != permitted:
        raise ValueError("Invalid bulk operation request.")
    return value


@login_required
@require_POST
def bulk_delete_jobs(request):
    """Delete selected inactive rows, or every draft/completed slice, atomically.

    No source files or G-code assets are deleted by this endpoint. Do not
    select an active queued/running row or perform a partial deletion.
    """
    if not request.user.has_perm("core.delete_slicejob"):
        return _error("You do not have permission to delete slicing jobs.", 403)
    try:
        data = _payload(request, {"mode", "ids"})
        mode = data.get("mode")
        if mode not in {"selected", "drafts", "slices"}:
            raise ValueError("Choose selected entries, all drafts or all completed slices.")
        ids = data.get("ids")
        if mode == "selected":
            if (not isinstance(ids, list) or not 1 <= len(ids) <= MAX_SELECTED
                    or len(set(map(str, ids))) != len(ids)):
                raise ValueError("Select 1–200 distinct slicing entries.")
            try:
                selected_ids = [uuid.UUID(item) for item in ids
                                if isinstance(item, str)]
            except (ValueError, AttributeError):
                raise ValueError("Invalid slicing entry identifier.") from None
            if len(selected_ids) != len(ids):
                raise ValueError("Invalid slicing entry identifier.")
        elif ids is not None:
            raise ValueError("All-entry deletion does not accept selected IDs.")
    except (ValueError, TypeError, UnicodeDecodeError) as exc:
        return _error(str(exc))
    with transaction.atomic():
        own = SliceJob.objects.select_for_update().filter(owner=request.user)
        if mode == "selected":
            rows = list(own.filter(pk__in=selected_ids).only("id", "status")[:MAX_SELECTED + 1])
            if len(rows) != len(selected_ids):
                return _error("One or more selected entries are missing. Refresh your drafts.", 409)
        else:
            rows = list(own.filter(status="draft" if mode == "drafts" else "completed")
                        .only("id", "status")[:MAX_BULK + 1])
            if len(rows) > MAX_BULK:
                return _error("Too many jobs to delete at once. Use a smaller selection.", 409)
        if any(row.status not in INACTIVE for row in rows):
            return _error("Active queued or running slicing jobs cannot be deleted.", 409)
        deleted_ids = [row.pk for row in rows]
        # Individual deletes follow the same preserve-files semantics as job_detail.
        # Saved projects, private generated outputs, and uploaded STL assets stay.
        for row in rows:
            row.delete()
    return JsonResponse({"deleted": len(deleted_ids),
                         "deleted_ids": [str(key) for key in deleted_ids],
                         "files_preserved": True})


def _private_output(asset):
    meta = asset.metadata or {}
    return (asset.category == "other"
            and meta.get("generated_by") == "makervault-slicer"
            and meta.get("extension") == ".gcode"
            and isinstance(meta.get("slice_job_id"), str)
            and bool(meta["slice_job_id"]))


@login_required
@require_POST
def remove_unsaved_gcode(request):
    """Purge only original slicer private G-code, never promoted library G-code.

    Matched completed jobs remain in history as stale/without preview. Exact
    source fields protect files a user uploaded or saved to the G-code Library.
    A deletion is refused if a non-completed job still references the output.
    """
    if not request.user.has_perm("core.delete_slicejob"):
        return _error("You do not have permission to remove private slicing output.", 403)
    try:
        if request.body.strip() not in (b"", b"{}"):
            raise ValueError("Unsaved G-code cleanup does not accept file IDs or filters.")
    except ValueError as exc:
        return _error(str(exc))
    # The metadata is generated by MakerVault, never supplied by the caller.
    with transaction.atomic():
        assets = list(FileAsset.objects.select_for_update().filter(
            owner=request.user, category="other",
            metadata__generated_by="makervault-slicer",
            metadata__extension=".gcode",
        )[:MAX_BULK + 1])
        if len(assets) > MAX_BULK:
            return _error("Too many private G-code files. Cleanup was not started.", 409)
        removed_ids = []
        for asset in assets:
            if not _private_output(asset):
                continue
            refs = list(SliceJob.objects.select_for_update().filter(
                output_asset=asset).only("id", "owner_id", "status"))
            if (any(job.owner_id != request.user.pk
                    or job.status != "completed" for job in refs)
                    or any(str(job.pk) != (asset.metadata or {}).get("slice_job_id")
                           for job in refs)):
                # Never break an active/inconsistent or shared output link.
                continue
            # For an orphaned output, exact generated_by/extension/job ID and
            # unsaved category are still required. Library G-code never matches.
            for job in refs:
                job.output_asset = None
                job.status = "stale"
                job.message = "Private unsaved G-code removed; slice history retained."
                job.save(update_fields=["output_asset", "status", "message", "updated_at"])
            storage = asset.file.storage if asset.file else None
            name = asset.file.name if asset.file else ""
            try:
                asset.delete()
            except ProtectedError:
                # A protected external relationship must not be bypassed.
                raise
            if storage and name:
                def erase(st=storage, filename=name):
                    try:
                        st.delete(filename)
                    except OSError:
                        LOG.exception("Could not delete private generated G-code from storage")
                transaction.on_commit(erase)
            removed_ids.append(str(asset.pk))
    return JsonResponse({
        "removed": len(removed_ids), "removed_ids": removed_ids,
        "saved_library_preserved": True, "source_files_preserved": True,
    })
