"""Validate and import slicer-generated G-code as private FileAssets.

Not connected to any HTTP endpoint or worker queue yet. No printer commands,
automatic spool deduction or job creation occur in this module.
"""
from django.core.files.base import ContentFile
from django.db import transaction
from django.core.exceptions import ValidationError
import hashlib
import re

from .gcode_analysis import MAX_SCAN_BYTES, analyse_text, compare_printer_metadata
from .models import FileAsset, SliceJob
from .slicer_paint_assets import settings_use_paint_field
from .slicer_gcode_thumbnails import add_gcode_thumbnails
from .storage_usage import ensure_storage_capacity


MAX_OUTPUT = MAX_SCAN_BYTES
DANGEROUS = re.compile(r"^\s*(?:N\d+\s+)?(?:M112|M500|M501|M502|M997)(?:\s|$)", re.I)


class SlicerOutputError(ValueError):
    pass


def inspect_generated_gcode(raw: bytes, printer=None) -> dict:
    if not isinstance(raw, bytes) or not 0 < len(raw) <= MAX_OUTPUT:
        raise SlicerOutputError("Generated G-code is empty or exceeds the inspected-size limit.")
    if b"\x00" in raw:
        raise SlicerOutputError("Binary G-code is not supported by this release.")
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        raise SlicerOutputError("Generated G-code is not valid UTF-8.") from None
    for line in text.splitlines():
        stripped = line.lstrip()
        if stripped.startswith(";"):
            continue
        code = stripped.split(";", 1)[0].strip()
        if DANGEROUS.match(code):
            raise SlicerOutputError("Output includes unsupported firmware-control commands.")
    report = analyse_text(text)
    if report.get("xy_moves", 0) <= 0:
        raise SlicerOutputError("Generated output contains no XY toolpath motion.")
    if printer is not None:
        match = compare_printer_metadata(report, printer)
        if match["status"] == "mismatch":
            raise SlicerOutputError("Generated file targets a different printer.")
        report["target_review"] = match
    return report


def generated_slice_name(job):
    """Derive a readable output filename from the models on the build plate."""
    ids = [item.get("asset_id") for item in (job.settings or {}).get("plate_objects", [])
           if isinstance(item, dict) and item.get("asset_id")]
    if not ids:
        ids = [str(job.input_asset_id)]
    assets = {str(asset.pk): asset for asset in FileAsset.objects.filter(
        owner_id=job.owner_id, pk__in=set(ids))}
    names = []
    for asset_id in ids:
        asset = assets.get(str(asset_id))
        if not asset:
            continue
        original = str((asset.metadata or {}).get("original_name") or asset.name or "Model")
        base = original.replace("\\", "/").rsplit("/", 1)[-1]
        if base.lower().endswith(".stl"):
            base = base[:-4]
        base = re.sub(r'[\x00-\x1f\x7f<>:"/\\|?*]', "_", base).strip(" ._")
        names.append(base or "Model")
    if not names:
        names = ["Model"]
    if len(names) == 1:
        label = names[0][:56]
    else:
        # Give both models space even when the first source filename is long.
        label = " + ".join(name[:22].rstrip(" ._") for name in names[:2])
        if len(names) > 2:
            label += f" +{len(names) - 2} more"
    # Keep the visible name compact; the encrypted blob key is independent.
    label = label[:56].rstrip(" ._") or "Model"
    return label + ".gcode"

def store_generated_gcode(job_id, raw: bytes):
    """Called by the approved worker dispatcher after a verified slice result.

    Idempotence: only an owned, running job with no existing output is accepted.
    """
    stored = None
    try:
        with transaction.atomic():
            job = SliceJob.objects.select_for_update(of=("self",)).select_related(
                "owner", "input_asset", "printer", "printer__catalog_model",
                "printer__printer_manufacturer",
            ).get(pk=job_id)
            if job.status != "running" or job.output_asset_id:
                raise SlicerOutputError("Job is not awaiting a new G-code result.")
            if job.input_asset.owner_id != job.owner_id or job.printer.owner_id != job.owner_id:
                raise SlicerOutputError("Slice job ownership changed.")
            # The validated engine output remains authoritative. Thumbnail
            # fallback changes comment-only metadata, never toolpath commands.
            prusa_offline = (job.engine == "prusaslicer" and (
                (job.settings or {}).get("multi_material_test") is True or
                any(settings_use_paint_field(job.owner, job.settings or {}, field)
                    for field in ("colour_paint", "support_paint", "seam_paint",
                                  "fuzzy_skin_paint", "variable_layer_profile"))
            ))
            # An offline Prusa native-printer research slice is not a claim
            # that the user's registered physical device can run that G-code.
            # Still validate text, motion, size and forbidden firmware control.
            report = inspect_generated_gcode(
                raw, None if prusa_offline else job.printer)
            if prusa_offline:
                report["target_review"] = {
                    "status": "offline_native_only",
                    "reason": "No physical Prusa printer/firmware compatibility approval.",
                }
            # Thumbnail generation is best-effort presentation metadata:
            # renderer failures or oversized PNG blocks must never invalidate a
            # previously validated, working printer toolpath.
            original_raw = raw
            thumbnail_sizes = ()
            try:
                enriched, candidate_sizes = add_gcode_thumbnails(raw)
                if len(enriched) <= MAX_OUTPUT:
                    raw, thumbnail_sizes = enriched, candidate_sizes
            except (ValueError, OSError, OverflowError, MemoryError):
                raw = original_raw
            ensure_storage_capacity(job.owner, len(raw))
            output_name = generated_slice_name(job)
            keep_in_library = (job.settings or {}).get("save_gcode_to_library") is True
            variable_test = settings_use_paint_field(
                job.owner, job.settings or {}, "variable_layer_profile")
            support_test = settings_use_paint_field(
                job.owner, job.settings or {}, "support_paint")
            seam_test = settings_use_paint_field(
                job.owner, job.settings or {}, "seam_paint")
            fuzzy_test = settings_use_paint_field(
                job.owner, job.settings or {}, "fuzzy_skin_paint")
            colour_test = settings_use_paint_field(
                job.owner, job.settings or {}, "colour_paint")
            combined_native_test = sum(bool(flag) for flag in
                (variable_test, support_test, seam_test, fuzzy_test)) > 1
            stored = FileAsset(
                owner=job.owner,
                project=job.input_asset.project,
                name=output_name,
                category="gcode" if keep_in_library else "other",
                sha256=hashlib.sha256(raw).hexdigest(),
                description="Generated by MakerVault Slicer; printer submission is separate.",
                metadata={
                    "extension": ".gcode", "original_name": output_name,
                    "size_bytes": len(raw), "generated_by": "makervault-slicer",
                    "slicer_library_status": "saved" if keep_in_library else "pending",
                    "slice_job_id": str(job.pk), "engine": job.engine,
                    "engine_version": job.engine_version,
                    "input_asset_id": str(job.input_asset_id),
                    "printer_id": str(job.printer_id),
                    "source_review": report.get("target_review", {}),
                    **({"prusa_offline_native": True, "printer_submission_verified": False}
                       if prusa_offline else {}),
                    "embedded_thumbnail_sizes": [
                        f"{size}x{size}" for size in thumbnail_sizes
                    ],
                    **({"multi_material_test": True, "printer_submission_verified": False}
                       if (job.settings or {}).get("multi_material_test") is True else {}),
                    **({"variable_layer_test": True, "printer_submission_verified": False}
                       if variable_test else {}),
                    **({"support_paint_test": True, "printer_submission_verified": False}
                       if support_test else {}),
                    **({"seam_paint_test": True, "printer_submission_verified": False}
                       if seam_test else {}),
                    **({"fuzzy_skin_paint_test": True, "printer_submission_verified": False}
                       if fuzzy_test else {}),
                },
            )
            stored.file = ContentFile(raw, name=output_name)
            stored.full_clean()
            stored.save()
            job.output_asset = stored
            job.status = "completed"
            job.progress = 100
            job.message = (
                "Creality colour-painted G-code generated; verify that both tools "
                "extrude inside the model before any supervised printer test."
                if (job.engine == "crealityprint"
                    and (job.settings or {}).get("multi_material_test") is True
                    and len((job.settings or {}).get("plate_objects") or []) == 1
                    and colour_test)
                else "Multi-colour G-code test completed and tool extrusion audited. "
                "Check printer readiness and explicitly confirm any supervised start."
                if (job.engine == "crealityprint"
                    and (job.settings or {}).get("multi_material_test") is True)
                else "Multi-colour G-code test completed and tool extrusion audited. "
                "Printer upload and print start remain disabled."
                if (job.settings or {}).get("multi_material_test") is True
                else "Combined native painting/layer test slice completed. Inspect every requested toolpath effect; printer upload remains disabled."
                if combined_native_test
                else "Variable layer-height test slice completed. Verify generated layer transitions; printer upload remains disabled."
                if variable_test
                else "Support painting test slice completed. Inspect native support paths; printer upload remains disabled."
                if support_test
                else "Seam painting test slice completed. Inspect G-code seam placement; printer upload remains disabled."
                if seam_test
                else "Painted fuzzy skin test completed. Inspect actual texture paths; printer upload remains disabled."
                if fuzzy_test
                else ("G-code saved to MakerVault library. Inspect before printing."
                      if keep_in_library else
                      "G-code retained with slice job; add it to the library when ready.")
            )
            job.save(update_fields=["output_asset", "status", "progress", "message", "updated_at"])
            return stored
    except Exception:
        # File writes may have succeeded before a later DB/transaction error.
        # Preserve DB correctness while cleaning up an unreferenced blob.
        if stored is not None and stored.file and stored.pk:
            try:
                if not FileAsset.objects.filter(pk=stored.pk).exists():
                    stored.file.delete(save=False)
            except Exception:
                pass
        raise
