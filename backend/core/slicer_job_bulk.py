"""Owner-scoped, explicitly confirmed bulk slicer-history and private-output cleanup.

This module never acts on printer submissions. G-code saved in the library
(category='gcode') and original STL/model sources remain untouched.
"""
import logging
import uuid
import base64
import re

from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.db.models.deletion import ProtectedError
from django.http import JsonResponse, HttpResponse
from django.views.decorators.http import require_POST, require_GET

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
            storage = asset.file.storage if asset.file else None
            name = asset.file.name if asset.file else ""
            try:
                # A savepoint protects any linked history if another module
                # references this file with a PROTECT foreign key.
                with transaction.atomic():
                    for job in refs:
                        job.output_asset = None
                        job.status = "stale"
                        job.message = "Private unsaved G-code removed; slice history retained."
                        job.save(update_fields=[
                            "output_asset", "status", "message", "updated_at"])
                    asset.delete()
            except ProtectedError:
                # Leave protected asset + slice history completely unchanged.
                continue
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


# Extract only the already embedded thumbnail. Generating thumbnail previews
# from arbitrary G-code on a web request would be expensive and unnecessary.
_THUMBNAIL_START = re.compile(
    rb"^;\s*thumbnail(?:_PNG)?\s+begin\s+(96x96|300x300)\s+([0-9]{1,7})\s*$", re.I)
_THUMBNAIL_END = re.compile(rb"^;\s*thumbnail(?:_PNG)?\s+end\s*$", re.I)
_B64_LINE = re.compile(rb"^;\s*([A-Za-z0-9+/=]+)\s*$")
_MAX_THUMBNAIL_SCAN = 2 * 1024 * 1024
_MAX_THUMBNAIL_B64 = 500 * 1024


def _embedded_thumbnail(data):
    """Read 96x96/300x300 base64 PNG thumbnails in the existing G-code header."""
    active = False
    length = 0
    chunks = []
    total = 0
    for raw_line in data.splitlines():
        line = raw_line.strip()
        if not active:
            found = _THUMBNAIL_START.fullmatch(line)
            if found:
                length = int(found.group(2))
                if not 0 < length <= _MAX_THUMBNAIL_B64:
                    continue
                active = True
            continue
        if _THUMBNAIL_END.fullmatch(line):
            if total != length:
                return None
            try:
                png = base64.b64decode(b"".join(chunks), validate=True)
            except (ValueError, base64.binascii.Error):
                return None
            if len(png) > 400 * 1024 or not png.startswith(b"\x89PNG\r\n\x1a\n"):
                return None
            return png
        group = _B64_LINE.fullmatch(line)
        if not group:
            return None
        part = group.group(1)
        total += len(part)
        if total > length:
            return None
        chunks.append(part)
    return None


@login_required
@require_GET
def job_thumbnail(request, job_id):
    """Owner-only read of a generated G-code's existing embedded PNG thumbnail."""
    job = SliceJob.objects.select_related("output_asset").filter(
        pk=job_id, owner=request.user, status="completed",
        output_asset__owner=request.user,
    ).first()
    if not job or not job.output_asset_id:
        return _error("No completed generated G-code thumbnail.", 404)
    asset = job.output_asset
    if not asset.file or asset.category not in {"other", "gcode"}:
        return _error("No generated G-code thumbnail.", 404)
    try:
        with asset.file.open("rb") as stream:
            header = stream.read(_MAX_THUMBNAIL_SCAN)
    except OSError:
        return _error("G-code thumbnail unavailable.", 404)
    png = _embedded_thumbnail(header)
    if not png:
        return _error("This slice has no embedded PNG thumbnail.", 404)
    response = HttpResponse(png, content_type="image/png")
    response["Cache-Control"] = "private, max-age=300"
    response["X-Content-Type-Options"] = "nosniff"
    return response
