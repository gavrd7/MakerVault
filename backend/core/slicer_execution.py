"""Explicitly gated queue/execution lifecycle for one isolated engine.

Nothing in this module starts a printer, changes spool stock or installs engines.
Execution requires a digest-pinned, healthy isolated worker and owner-scoped
native profiles with validated content and intact inheritance chains.
"""
import hashlib
import json
import logging
import math
import uuid
import os
from datetime import timedelta
from django.db import transaction
from django.utils import timezone

from .models import SliceJob, FileAsset, SlicerProfile
from .slicer_engines import validate_engine_selection
from .slicer_output import store_generated_gcode
from .slicer_native_resolution import resolved_native_profile
from .slicer_bed_dimensions import trusted_plate_dimensions
from .slicer_material_routing import single_material_slice_assignment, MaterialRoutingError
from .slicer_multimaterial_execution import (plan_native_multimaterial, prepare_job_multimaterial,
                                             prepare_creality_multistl)
from .slicer_material_gcode_audit import audit_native_tool_usage, MaterialGcodeAuditError
from .slicer_flush_settings import apply_orca_flush_settings
from .slicer_native_overrides import apply_orca_job_overrides
from .slicer_variable_layers import audit_orca_variable_layers, validate_orca_variable_support_compatibility
from .slicer_paint_assets import expand_painted_settings
from .slicer_process_settings import apply_process_overrides
from .slicer_plate_3mf import build_plate_3mf, build_compound_plate_3mf
from .slicer_plate_validation import validate_plate_collisions, PlateCollisionError
from .slicer_worker_client import SlicerWorkerError, health, run_remote_job


logger = logging.getLogger(__name__)

MAX_INPUT = 32 * 1024 * 1024
MAX_PROFILE = 1024 * 1024


class SlicerExecutionError(ValueError):
    pass


_MACHINE_IDENTITY_FIELDS = (
    "printer_model", "printer_variant", "nozzle_diameter",
    "printable_area", "printable_height", "bed_exclude_area",
)


def _execution_printer_profile(printer_profile, resolved_printer, resolved_process):
    """Use an authenticated native source identity for a compatible custom copy.

    A custom preset has a user-facing unique name, while official process
    profiles can list *only* its upstream native machine name under
    compatible_printers. Preserve the copy's settings but use the original
    machine name in the in-memory worker payload, only when the custom and
    upstream machine model/nozzle/build geometry are identical and the
    process was explicitly compatible with that upstream machine.

    No stored profiles, process compatibility lists, or printer hardware
    are modified. Unknown or changed machine geometry fails closed.
    """
    if printer_profile.engine != "orcaslicer":
        return resolved_printer
    try:
        current = json.loads(resolved_printer)
        process = json.loads(resolved_process)
    except (ValueError, TypeError):
        raise SlicerExecutionError("Selected native printer or process JSON is invalid.") from None
    allowed = process.get("compatible_printers")
    if not isinstance(allowed, list) or not allowed:
        return resolved_printer
    native_name = current.get("name")
    if isinstance(native_name, str) and native_name in allowed:
        return resolved_printer
    metadata = printer_profile.file_asset.metadata or {}
    source_id = metadata.get("slicer_custom_source_profile_id")
    if not isinstance(source_id, str):
        raise SlicerExecutionError(
            "Selected process preset does not recognise this native printer profile. "
            "Select a process preset compatible with the printer."
        )
    try:
        source_uuid = uuid.UUID(source_id)
    except ValueError:
        raise SlicerExecutionError("Custom printer profile has an invalid native source identity.") from None
    source = SlicerProfile.objects.filter(
        pk=source_uuid, owner_id=printer_profile.owner_id,
        engine=printer_profile.engine, engine_version=printer_profile.engine_version,
        kind="printer",
    ).select_related("file_asset").first()
    if not source:
        raise SlicerExecutionError(
            "The original native machine preset for this custom profile is missing. "
            "Restore its official parent chain or choose a matching process preset."
        )
    from .slicer_profiles import SlicerProfileError
    try:
        original = json.loads(resolved_native_profile(source))
    except (SlicerProfileError, ValueError, OSError) as exc:
        raise SlicerExecutionError("Original native printer profile cannot be safely resolved.") from exc
    if (
        not isinstance(original.get("name"), str) or original["name"] not in allowed
        or any(current.get(key) != original.get(key) for key in _MACHINE_IDENTITY_FIELDS)
    ):
        raise SlicerExecutionError(
            "This custom printer changes machine identity, nozzle or build geometry "
            "and cannot use the selected process preset without compatibility review."
        )
    logger.info("Slicing with native source machine identity for compatible custom printer preset")
    return json.dumps(
        {**current, "name": original["name"]}, ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")


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
    configured = (os.environ.get("MAKERVAULT_SLICER_ENGINES_JSON", "")
                  if os.environ.get("MAKERVAULT_SLICER_HOST_UPDATER_ENABLED") != "1"
                  else "")
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
    # When the isolated engine installer is present, the worker reads an
    # atomically activated manifest from its read-only versioned engine store.
    # Each entry is checked by the worker against its actual on-disk digest;
    # no administrator-managed environment approval list is required.
    if os.environ.get("MAKERVAULT_SLICER_HOST_UPDATER_ENABLED") == "1":
        installed = {}
        for engine, entry in health_engines.items():
            version, checksum = entry.get("version"), entry.get("binary_sha256")
            if not (entry.get("ready") is True and isinstance(version, str)
                    and isinstance(checksum, str)):
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


def _plate_builder(objects_with_stl):
    """Select the independent-object path only for saved native overrides.

    Existing global-only multi-model jobs retain the previously verified
    compound geometry path, preserving working K1/K2 single-filament slices.
    Admission still rejects per-object jobs until real-binary proof exists.
    """
    return (build_plate_3mf if any(
        isinstance(item, dict) and (bool(item.get("process_overrides")) or
            bool((item.get("variable_layer_profile") or {}).get("bands")) or
            bool((item.get("support_paint") or {}).get("regions")) or
            bool((item.get("seam_paint") or {}).get("regions")) or
            bool((item.get("fuzzy_skin_paint") or {}).get("regions")))
        for item, _raw in objects_with_stl
    ) else build_compound_plate_3mf)


# Real OrcaSlicer 2.4.2 binary acceptance: two separate equal cubes,
# 2 walls/15% infill versus 5 walls/37% infill, both geometry regions and
# distinct measured extrusion in a single G-code job. Other native process
# options remain draft-only until independently verified with the worker.
VERIFIED_OBJECT_PROCESS_KEYS = frozenset({
    "wall_loops", "sparse_infill_density",
})


def _validate_plate_execution(job):
    """An untouched STL or a bounded native-bed-backed multi-object 3MF plate."""
    try:
        settings=expand_painted_settings(getattr(job, "owner", None), job.settings or {})
    except (ValueError, OSError) as exc:
        raise SlicerExecutionError("A referenced private painting asset is missing or invalid.") from exc
    # Do not silently discard native flush / prime-tower preferences when
    # admitting an otherwise single-filament job. They require the future
    # exact-printer, multi-tool worker route and verified CFS bindings.
    if (settings.get("flush_settings") is not None and
            settings.get("multi_material_test") is not True):
        raise SlicerExecutionError(
            "This saved job contains flushing changes but was not marked for native "
            "multi-material slicing. Create a new slice from the draft using Slice "
            "with at least two mapped filaments. Printer submission remains "
            "disabled for offline multi-material test G-code."
        )
    objects=settings.get("plate_objects")
    project=settings.get("plates")
    if project is not None:
        active=next((plate for plate in project
                     if plate.get("id")==settings.get("active_plate_id")), None)
        if not active or not active.get("objects"):
            raise SlicerExecutionError(
                "The active build plate is empty. Choose a populated plate before slicing.")
        if objects!=active["objects"]:
            raise SlicerExecutionError(
                "The active build plate does not match the saved slicing model list.")
    if not objects:
        if settings.get("slot_filament_profiles") or settings.get("material_tool_bindings"):
            raise SlicerExecutionError("Remove unused slot-specific filament profiles and tool bindings before slicing.")
        return True
    # Saved CFS/AMS/head mappings are advisory until the native palette,
    # toolchange commands, and chosen machine topology have passed pinned
    # worker + printer verification. Do NOT silently merge distinct material
    # assignments into a single-filament print.
    if (settings.get("multi_material_test") is not True and
            any(isinstance(item, dict) and isinstance(item.get("colour_paint"), dict)
                and (item["colour_paint"].get("faces") or item["colour_paint"].get("regions"))
                for item in objects)):
        raise SlicerExecutionError(
            "This saved job contains colour painting but was not marked for native "
            "multi-material slicing. Create a new slice from the painted draft using "
            "Slice; one model with two mapped filaments is supported. "
            "Painted colours cannot be discarded by the single-material engine."
        )
    if any(isinstance(item, dict) and isinstance(item.get("support_paint"), dict)
           and item["support_paint"].get("regions") for item in objects):
        # Native geometry splitting and paint_supports attributes are
        # experimental until compared with real Orca-generated toolpaths.
        if job.engine != "orcaslicer" or job.engine_version != "2.5.0":
            raise SlicerExecutionError(
                "Native support painting test requires OrcaSlicer 2.5.0.")
        if len(objects) != 1 or settings.get("multi_material_test"):
            raise SlicerExecutionError(
                "Support painting test requires one single-filament model.")
        item = objects[0]
        if item.get("process_overrides"):
            raise SlicerExecutionError(
                "Support painting with per-object overrides is not verified.")
        if (any(abs(float(value)) > 0.000001 for value in
                item.get("rotation_xyz_deg", [0, 0]))
                or abs(float(item.get("z_mm", 0))) > 0.000001):
            raise SlicerExecutionError(
                "Support painting test requires an upright, non-elevated model.")
        if any(abs(float(value) - 100) > 0.000001 for value in
               item.get("scale_xyz_percent", [item.get("scale_percent", 100)] * 3)):
            raise SlicerExecutionError(
                "Support painting test requires an unscaled model.")
    if any(isinstance(item, dict) and isinstance(item.get("seam_paint"), dict)
           and item["seam_paint"].get("regions") for item in objects):
        if job.engine != "orcaslicer" or job.engine_version != "2.5.0":
            raise SlicerExecutionError("Native seam painting test requires OrcaSlicer 2.5.0.")
        if len(objects) != 1 or settings.get("multi_material_test"):
            raise SlicerExecutionError("Seam painting test requires one single-filament model.")
        item = objects[0]
        if item.get("process_overrides"):
            raise SlicerExecutionError("Seam painting with per-object overrides is not yet verified.")
        if (any(abs(float(value)) > 0.000001 for value in
                item.get("rotation_xyz_deg", [0, 0]))
                or abs(float(item.get("z_mm", 0))) > 0.000001):
            raise SlicerExecutionError("Seam painting test requires an upright, non-elevated model.")
        if any(abs(float(value)-100) > 0.000001 for value in
               item.get("scale_xyz_percent", [item.get("scale_percent", 100)] * 3)):
            raise SlicerExecutionError("Seam painting test requires an unscaled model.")
    if any(isinstance(item, dict) and isinstance(item.get("fuzzy_skin_paint"), dict)
           and item["fuzzy_skin_paint"].get("regions") for item in objects):
        # Orca 2.5 saves painted fuzzy regions in paint_fuzzy_skin and uses
        # fuzzy_skin=none ("Painted only") to activate them. The distinct
        # disabled_fuzzy value turns the effect off entirely.
        if job.engine != "orcaslicer" or job.engine_version != "2.5.0":
            raise SlicerExecutionError(
                "Native fuzzy skin painting test requires OrcaSlicer 2.5.0.")
        if len(objects) != 1 or settings.get("multi_material_test"):
            raise SlicerExecutionError(
                "Selective fuzzy skin test requires one single-filament model.")
        item = objects[0]
        if item.get("process_overrides"):
            raise SlicerExecutionError(
                "Fuzzy skin painting with per-object overrides is not verified.")
        if (any(abs(float(value)) > 0.000001 for value in
                item.get("rotation_xyz_deg", [0, 0]))
                or abs(float(item.get("z_mm", 0))) > 0.000001):
            raise SlicerExecutionError(
                "Fuzzy skin painting test requires an upright, non-elevated model.")
        if any(abs(float(value) - 100) > 0.000001 for value in
               item.get("scale_xyz_percent", [item.get("scale_percent", 100)] * 3)):
            raise SlicerExecutionError(
                "Fuzzy skin painting test requires an unscaled model.")
    if any(isinstance(item, dict) and isinstance(item.get("variable_layer_profile"), dict)
           and item["variable_layer_profile"].get("bands") for item in objects):
        # Native Orca layer_config_ranges.xml export is available for an
        # explicitly offline, single upright model experiment only. Real
        # G-code and firmware checks are still needed for print approval.
        if job.engine != "orcaslicer" or job.engine_version != "2.5.0":
            raise SlicerExecutionError(
                "Variable layer test slicing currently requires OrcaSlicer 2.5.0.")
        if len(objects) != 1 or settings.get("multi_material_test"):
            raise SlicerExecutionError(
                "Variable layer test slicing currently requires one single-material model.")
        item = objects[0]
        if any(abs(float(x)) > 0.000001 for x in
               item.get("rotation_xyz_deg", [0, 0])) or abs(float(item.get("z_mm", 0))) > 0.000001:
            raise SlicerExecutionError(
                "Variable layer test slicing requires an upright, non-elevated model.")
        if any(abs(float(x) - 100) > 0.000001 for x in
               item.get("scale_xyz_percent", [item.get("scale_percent", 100)] * 3)):
            raise SlicerExecutionError(
                "Variable layer test slicing requires an unscaled model.")
        if any(item.get("process_overrides") for item in objects):
            raise SlicerExecutionError(
                "Combine variable layer height with Object settings after the native test fixture.")
    if settings.get("multi_material_test") is True:
        if job.engine == "crealityprint":
            if not (settings.get("creality_auto_arrange_offline") is True
                    and len(objects) == 2):
                raise SlicerExecutionError(
                    "Creality multi-material requires two STLs and explicit offline auto-arrangement.")
            if settings.get("flush_settings") is not None or settings.get("prime_tower") is not None:
                raise SlicerExecutionError(
                    "Creality's offline multi-STL test cannot preserve custom flushing or prime tower positions.")
            if any((item.get("colour_paint") or {}).get("regions") or
                   (item.get("colour_paint") or {}).get("faces") or
                   item.get("support_paint") or item.get("seam_paint") or
                   item.get("fuzzy_skin_paint") or item.get("variable_layer_profile") or
                   item.get("process_overrides")
                   for item in objects):
                raise SlicerExecutionError(
                    "Creality native multi-STL testing cannot include painting or per-object overrides.")
        elif settings.get("creality_auto_arrange_offline"):
            raise SlicerExecutionError("Creality auto-arrangement is incompatible with this engine.")
        # This permits *offline G-code generation* only. Uploaded or started
        # printer jobs are blocked by the submission API for these artifacts.
        try:
            plan_native_multimaterial(job, settings=settings)
            trusted_plate_dimensions(job.printer_profile)
        except (MaterialRoutingError, ValueError) as exc:
            raise SlicerExecutionError(str(exc)) from exc
        for item in objects:
            overrides = item.get("process_overrides") or {}
            if not isinstance(overrides, dict) or set(overrides) - VERIFIED_OBJECT_PROCESS_KEYS:
                raise SlicerExecutionError(
                    "Only verified per-object wall and infill overrides are supported in multi-colour tests."
                )
        return True
    # One physical bay can annotate an otherwise ordinary single-filament
    # Orca slice. Do not convert the bay number into a native tool index.
    try:
        single_material_slice_assignment(
            objects,
            printer_id=getattr(job, "printer_id", None),
            selected_filament_profile_id=getattr(job, "filament_profile_id", None),
            slot_filament_profiles=settings.get("slot_filament_profiles") or [],
            material_tool_bindings=settings.get("material_tool_bindings") or [],
        )
    except MaterialRoutingError as exc:
        raise SlicerExecutionError(str(exc)) from exc
    if job.engine not in {"orcaslicer", "crealityprint"}:
        raise SlicerExecutionError("This engine does not yet support native build-plate slicing.")
    if job.engine == "crealityprint":
        # Creality receives the same validated STL/3MF geometry route, but
        # Orca-only per-object modifiers must not be silently discarded.
        if any(isinstance(item, dict) and item.get("process_overrides") for item in objects):
            raise SlicerExecutionError(
                "Per-object process overrides are not yet supported by Creality Print.")
        if settings.get("process_overrides"):
            raise SlicerExecutionError(
                "Custom process overrides are not yet supported by Creality Print.")
        if settings.get("multi_material_test"):
            if not (settings.get("creality_auto_arrange_offline") is True and len(objects) == 2):
                raise SlicerExecutionError(
                    "Creality Print multi-material test requires two assigned STL models "
                    "and explicit offline auto-arrangement.")
            if settings.get("flush_settings") is not None or settings.get("prime_tower") is not None:
                raise SlicerExecutionError(
                    "Creality Print's offline multi-STL test cannot preserve custom "
                    "flush settings or prime tower positions.")
            if any((item.get("colour_paint") or {}).get("regions") or
                   (item.get("colour_paint") or {}).get("faces")
                   for item in objects):
                raise SlicerExecutionError(
                    "Creality colour-painted models require a future native 3MF route.")
    if not isinstance(objects, list) or not 1 <= len(objects) <= 12:
        raise SlicerExecutionError("Plate model list is invalid.")
    for item in objects:
        if not isinstance(item, dict):
            raise SlicerExecutionError("Invalid plate object.")
        overrides = item.get("process_overrides") or {}
        if not isinstance(overrides, dict):
            raise SlicerExecutionError("Invalid per-object process settings.")
        if set(overrides) - VERIFIED_OBJECT_PROCESS_KEYS:
            raise SlicerExecutionError(
                "This draft uses per-object settings that have not passed real Orca "
                "G-code verification. Wall loops and sparse infill density are "
                "currently verified; save the draft to retain other settings."
            )
    if not job.printer_profile_id:
        raise SlicerExecutionError("Select a native printer profile for slicing.")
    # The single unchanged STL execution path uses Orca's native arrange
    # rather than producing a 3MF plate. It must not be gated by the stricter
    # geometry validation reserved for generated 3MF placement.
    if _single_unmodified_stl(objects):
        return True
    try:
        trusted_plate_dimensions(job.printer_profile)
    except ValueError as exc:
        raise SlicerExecutionError(
            "Edited or multi-model 3MF plate requires supported native rectangular "
            "build dimensions; review the selected printer profile."
        ) from exc
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
        plate = (job.settings or {}).get("plate_objects") or []
        if len(plate) > 1:
            # The UI disables conflicting plates, but an older saved draft
            # or a direct API call must not bypass the same safety rule.
            owned = {str(row.pk): row for row in FileAsset.objects.filter(
                pk__in=[item["asset_id"] for item in plate],
                owner_id=job.owner_id, category="mesh")}
            try:
                validate_plate_collisions([(
                    item, _read_owned_file(owned[str(item["asset_id"])],
                                           job.owner_id, MAX_INPUT, "Plate STL")
                ) for item in plate])
            except (KeyError, PlateCollisionError, ValueError) as exc:
                raise SlicerExecutionError(
                    "Build plate models overlap or cannot be checked. "
                    "Open the draft and resolve the highlighted conflicts before slicing."
                ) from exc
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


def _single_unmodified_stl(plate):
    """Only bypass 3MF when Orca's native STL arrange preserves user intent.

    Any model repositioning, scaling or rotation remains on the explicit
    project path, where it can be reproduced faithfully.
    """
    if not isinstance(plate, list) or len(plate) != 1 or not isinstance(plate[0], dict):
        return False
    item = plate[0]
    if (item.get("process_overrides") or (item.get("variable_layer_profile") or {}).get("bands")
            or (item.get("support_paint") or {}).get("regions")
            or (item.get("seam_paint") or {}).get("regions")
            or (item.get("fuzzy_skin_paint") or {}).get("regions")):
        return False  # Native object or variable-layer settings must never fall back to plain STL.
    try:
        if any(float(item.get(key, 0) if key == "z_mm" else item[key]) != expected for key, expected in (
            ("x_mm", 0), ("y_mm", 0), ("z_mm", 0), ("rotation_deg", 0),
            ("scale_percent", 100),
        )):
            return False
        if any(abs(float(v)) > 1e-7 for v in item.get("rotation_xyz_deg", [0, 0])):
            return False
        xyz = item.get("scale_xyz_percent", [100, 100, 100])
        return isinstance(xyz, (list, tuple)) and len(xyz) == 3 and all(
            float(value) == 100 for value in xyz
        )
    except (ValueError, TypeError, KeyError, OverflowError):
        return False


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
        # Decode immutable private paint assets in memory only. The database
        # job retains compact references and is never overwritten with masks.
        job.settings = expand_painted_settings(job.owner, job.settings or {})
        model = _read_owned_file(job.input_asset, job.owner_id, MAX_INPUT, "Model")
        model_format = "stl"
        material_result = None
        is_multi_test = (job.settings or {}).get("multi_material_test") is True
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
            if is_multi_test:
                stage = "preparing the native multi-filament test plate"
                if job.engine == "crealityprint":
                    material_result = prepare_creality_multistl(job, source_models)
                    model = material_result["model_stls"][0]
                    model_format = "stl"
                else:
                    width, depth = trusted_plate_dimensions(job.printer_profile)
                    material_result = prepare_job_multimaterial(
                        job, source_models, bed_width=width, bed_depth=depth,
                    )
                    model = material_result["model_3mf"]
                    model_format = "3mf"
            elif _single_unmodified_stl(plate):
                # Avoid an unnecessary 3MF round trip for one untransformed
                # model. The validated native STL CLI path performs its own
                # auto-arrangement and uses the same approved profiles.
                model = source_models[0][1]
                model_format = "stl"
                logger.info("Slicing job %s: using direct validated STL path", job.pk)
            else:
                stage = "resolving native printer bed dimensions"
                width, depth = trusted_plate_dimensions(job.printer_profile)
                stage = "assembling the build plate 3MF"
                # Keep every object and its native settings when this route
                # eventually passes pinned-binary acceptance. The existing
                # queue admission still blocks unverified per-object jobs.
                # Ordinary single-material multi-object plates retain their
                # proven compound-mesh execution path.
                model = _plate_builder(source_models)(
                    source_models, bed_width=width, bed_depth=depth
                )
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
        if job.engine == "orcaslicer":
            stage = "checking native printer/process compatibility"
            profiles[0] = _execution_printer_profile(
                job.printer_profile, profiles[0], profiles[2]
            )
            stage = "checking native printer/process compatibility"
            try:
                profiles[2], profiles[1] = apply_orca_job_overrides(
                    profiles[2], profiles[1], job.plate,
                    (job.settings or {}).get("plate_objects") or [],
                    printer_profile=job.printer_profile,
                )
            except ValueError as exc:
                # Only server-authored, canonical plate names appear in this
                # diagnostic. Never silently substitute cool-plate settings.
                raise SlicerExecutionError(str(exc)) from exc
            profiles[2] = apply_process_overrides(
                profiles[2], (job.settings or {}).get("process_overrides") or {},
            )
            # Orca CLI otherwise exits 205 without identifying the conflicting
            # process setting. Keep the user's preset and requested paint intact.
            has_variable = any(
                isinstance(obj, dict) and
                bool((obj.get("variable_layer_profile") or {}).get("bands"))
                for obj in ((job.settings or {}).get("plate_objects") or [])
            )
            try:
                validate_orca_variable_support_compatibility(profiles[2], has_variable)
            except ValueError as exc:
                raise SlicerExecutionError(str(exc)) from exc
            if material_result is not None and (job.settings or {}).get("flush_settings") is not None:
                # Validated native process derivation, never a printer macro.
                # Painted regions can select a tool not used as the model's
                # default extruder, so the full ordered palette must supply
                # the physical slot-to-logical-tool mapping.
                from types import SimpleNamespace
                try:
                    ordered_routes = [
                        SimpleNamespace(slot_id=slot, tool_index=tool)
                        for slot, tool in material_result["tool_bindings"].items()
                    ]
                    profiles[2] = apply_orca_flush_settings(
                        profiles[2], job.settings["flush_settings"],
                        routes=ordered_routes,
                        tool_count=len(material_result["filament_profiles"]),
                        topology=material_result["topology"],
                    )
                except (MaterialRoutingError, ValueError) as exc:
                    raise SlicerExecutionError(str(exc)) from exc
            # Orca 2.5 accepts one X/Y value per plate. Apply the user's
            # placement after native process and flushing overrides.
            tower = (job.settings or {}).get("prime_tower")
            if tower is not None:
                try:
                    if not isinstance(tower, dict) or set(tower) != {"x", "y"}:
                        raise ValueError("Invalid position")
                    x, y = (tower[axis] for axis in ("x", "y"))
                    if any(isinstance(v, bool) or not isinstance(v, (int, float))
                           or not math.isfinite(v) for v in (x, y)):
                        raise ValueError("Invalid coordinate")
                    width, depth = trusted_plate_dimensions(job.printer_profile)
                    native = json.loads(profiles[2])
                    raw_width = native.get("prime_tower_width", "35")
                    native_width = float(raw_width[0] if isinstance(raw_width, list) else raw_width)
                    if not math.isfinite(native_width) or native_width <= 0:
                        raise ValueError("Invalid native tower width")
                    # The tower's exact depth is engine-computed after slice.
                    # The preview is explicitly approximate; use conservative
                    # border bounds here and retain Orca's own final checks.
                    if not (0 <= x <= width - native_width and 0 <= y < depth):
                        raise ValueError("Tower lies beyond the printable bed")
                    native["wipe_tower_x"] = [str(round(x, 3))]
                    native["wipe_tower_y"] = [str(round(y, 3))]
                    profiles[2] = json.dumps(native, ensure_ascii=False,
                                              separators=(",", ":")).encode("utf-8")
                except (ValueError, TypeError, KeyError, UnicodeDecodeError) as exc:
                    raise SlicerExecutionError("Invalid prime tower position for this printer.") from exc
            if material_result is not None:
                # The worker protocol checks byte equality between the legacy
                # first preset and the first member of the ordered palette.
                palette = list(material_result["filament_profiles"])
                palette[0] = profiles[1]
                material_result["filament_profiles"] = tuple(palette)
        if material_result is not None and job.engine == "crealityprint":
            # The first resolved palette entry is the authenticated job's
            # selected filament profile, as required by the worker protocol.
            palette = list(material_result["filament_profiles"])
            palette[0] = profiles[1]
            material_result["filament_profiles"] = tuple(palette)
        if model_format == "stl" and job.input_asset.sha256 and hashlib.sha256(model).hexdigest() != job.input_asset.sha256:
            raise SlicerExecutionError("Model contents changed since the job was prepared.")
        stage = "executing the isolated slicer worker"
        output = run_remote_job(
            job.pk, job.engine, job.engine_version, model,
            profiles[0], profiles[1], profiles[2],
            model_format=model_format,
            filament_profiles=(material_result["filament_profiles"]
                               if material_result is not None else None),
            creality_model_stls=(material_result["model_stls"]
                                if material_result is not None and job.engine == "crealityprint"
                                else None),
            creality_tool_ids=(material_result["tool_ids"]
                              if material_result is not None and job.engine == "crealityprint"
                              else None),
        )
        if material_result is not None:
            stage = "auditing multi-material tool selections and extrusion"
            try:
                audit_native_tool_usage(
                    output.decode("utf-8"),
                    expected_tools=set(material_result["expected_tools"]),
                )
            except (UnicodeDecodeError, MaterialGcodeAuditError) as exc:
                raise SlicerExecutionError(
                    "Multi-colour test G-code did not pass the native tool/extrusion audit."
                ) from exc
        variable_test = next((
            (item.get("variable_layer_profile") or {}).get("bands")
            for item in (job.settings or {}).get("plate_objects", [])
            if isinstance(item, dict) and (item.get("variable_layer_profile") or {}).get("bands")
        ), None)
        if variable_test:
            stage = "auditing native variable layer height"
            try:
                audit_orca_variable_layers(output.decode("utf-8"), variable_test)
            except (UnicodeDecodeError, ValueError) as exc:
                raise SlicerExecutionError(
                    "Orca did not produce verifiable native variable layer heights. "
                    "The generated G-code has not been approved or stored."
                ) from exc
        stage = "validating and storing generated G-code"
        asset = store_generated_gcode(job.pk, output)
        # Prepare GPU-friendly overviews outside the HTTP request and outside
        # the slicing transaction. The task is advisory: queue outages must
        # never turn a successfully stored slice into a failed job.
        try:
            from .tasks import warm_gcode_preview_task
            warm_gcode_preview_task.delay(str(asset.pk))
        except Exception:
            logger.warning("Preview warming could not be queued for %s", asset.pk, exc_info=True)
        return {"status": "completed", "asset_id": str(asset.pk)}
    except SlicerWorkerError as exc:
        # SlicerWorkerError uses fixed, sanitized status/stage/reason values;
        # unlike arbitrary worker response bodies these are safe in job status.
        logger.warning("Slicing job %s rejected: %s", job.pk, exc)
        with transaction.atomic():
            row = SliceJob.objects.select_for_update().filter(pk=job.pk).first()
            if row and row.status == "running":
                row.status = "failed"
                row.message = str(exc)[:240]
                row.save(update_fields=["status", "message", "updated_at"])
        return {"status": "failed"}
    except Exception as exc:
        # Only expose explicit, known-safe model-validation messages here.
        # Unrecognised errors still use a generic status; the real traceback
        # remains in MakerVault's application logs, not worker logs.
        from .slicer_profiles import SlicerProfileError
        diagnostic = None
        if stage == "assembling the build plate 3MF" and isinstance(exc, SlicerProfileError):
            diagnostic = str(exc)[:180]
        elif stage == "checking native printer/process compatibility" and isinstance(exc, SlicerExecutionError):
            # All messages in this branch are fixed, server-authored
            # compatibility guidance; no native preset contents are echoed.
            diagnostic = str(exc)[:180]
        elif stage == "auditing native variable layer height" and isinstance(exc, SlicerExecutionError):
            diagnostic = str(exc)[:180]
        logger.exception("Slicing job %s failed during %s", job.pk, stage)
        with transaction.atomic():
            row = SliceJob.objects.select_for_update().filter(pk=job.pk).first()
            if row and row.status == "running":
                row.status = "failed"
                row.message = (
                    ("Build-plate preparation failed: " + diagnostic)
                    if diagnostic and stage == "assembling the build plate 3MF"
                    else ("Native profile compatibility: " + diagnostic)
                    if diagnostic and stage == "checking native printer/process compatibility"
                    else ("Variable layer test failed: " + diagnostic)
                    if diagnostic and stage == "auditing native variable layer height"
                    else "Slicing failed during " + stage +
                    ". Check MakerVault application logs for this job."
                )[:240]
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
