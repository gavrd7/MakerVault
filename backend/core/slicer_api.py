"""Owner-scoped slicer drafts and engine discovery; no execution endpoints yet."""
import json
import io
import zipfile
import zlib
import os
import math
import re
import uuid
import hashlib
from pathlib import Path
from decimal import Decimal, InvalidOperation

from django.contrib.auth.decorators import login_required
from django.http import JsonResponse, HttpResponse
from django.urls import reverse
from django.db import IntegrityError, transaction
from django.db.models.deletion import ProtectedError
from django.core.cache import cache
from django.views.decorators.http import require_http_methods

from .models import FileAsset, Printer, PrinterConnection, SliceJob, Spool, SlicerProfile
from .slicer_engines import engine_catalogue, get_engine
from .slicer_capabilities import native_capabilities
from .slicer_profiles import SlicerProfileError, inspect_native_profile
from .slicer_profile_edit import SETTINGS as EDITABLE_PROFILE_SETTINGS, customise_native_json
from .slicer_profile_lineage import inspect_orca_lineage
from .slicer_native_resolution import resolved_native_profile
from .slicer_native_overrides import ORCA_PLATES
from .slicer_plate_types import inspect_engine_plates
from .slicer_process_settings import process_schema, validate_process_overrides, apply_process_overrides
from .slicer_modifier_volumes import validate_modifier_volumes, MAX_TOTAL_MODIFIERS
from .slicer_flush_settings import validate_flush_settings
from .slicer_colour_painting import validate_colour_paint
from .slicer_support_painting import validate_support_paint
from .slicer_semantic_painting import validate_semantic_paint
from .slicer_variable_layers import validate_variable_layer_profile
from .slicer_paint_assets import store_paint, load_paint, expand_painted_item, expand_painted_settings, PAINT_FIELDS
from .slicer_mesh import inspect_stl, MeshInspectionError, MAX_INSPECTION_BYTES
from .slicer_resource_budget import (input_model_budget, xml_geometry_budget,
    project_archive_budget, source_input_budget, memory_budget)
from .slicer_bed import inspect_orca_plate, inspect_creality_plate, inspect_bambu_plate
from .slicer_bed_artwork import (official_artwork_source, cached_official_artwork,
    official_bed_model_source, cached_official_bed_model)
from .slicer_official_chain import official_profile_chain
from .slicer_official_release_resolver import (
    resolve_official_release, approved_catalogue_versions, default_catalogue_version,
)
from .slicer_creality_official_profiles import (
    search_creality_profiles, fetch_creality_profile, available_creality_vendors,
    official_catalogue_models as creality_catalogue_models,
    ENGINE_VERSION as OFFICIAL_CRE_VERSION, SOURCE as OFFICIAL_CRE_SOURCE,
    REF as OFFICIAL_CRE_REF,
)
from .slicer_snapmaker_official_profiles import (
    search_snapmaker_profiles, fetch_snapmaker_profile, available_snapmaker_vendors,
    official_catalogue_models as snapmaker_catalogue_models,
    ENGINE_VERSION as OFFICIAL_SNAP_VERSION, SOURCE as OFFICIAL_SNAP_SOURCE,
    REF as OFFICIAL_SNAP_REF,
)
from .slicer_prusa_official_profiles import (
    search_prusa_profiles, fetch_prusa_model, fetch_prusa_profile, available_prusa_vendors,
    official_catalogue_models as prusa_catalogue_models,
    ENGINE_VERSION as OFFICIAL_PRUSA_VERSION, SOURCE as OFFICIAL_PRUSA_SOURCE,
    REF as OFFICIAL_PRUSA_REF,
)
from .slicer_bambu_official_profiles import (
    search_bambu_profiles, fetch_bambu_model, available_bambu_vendors,
    official_catalogue_models as bambu_catalogue_models,
    ENGINE_VERSION as OFFICIAL_BAMBU_VERSION, SOURCE as OFFICIAL_BAMBU_SOURCE,
    REF as OFFICIAL_BAMBU_REF,
)
from .slicer_bambu_native_profiles import (
    search_bambu_native_profiles, fetch_bambu_native_chain,
)
from .slicer_official_profiles import (
    OfficialProfileError, search_official_profiles, fetch_official_profile, available_official_vendors,
    official_filament_brands, APPROVED_VERSIONS as ORCA_APPROVED_PROFILE_VERSIONS,
    official_catalogue_models as orca_catalogue_models,
    ENGINE_VERSION as OFFICIAL_ORCA_VERSION, SOURCE as OFFICIAL_ORCA_SOURCE,
    REF as OFFICIAL_ORCA_REF,
)
from django.core.files.base import ContentFile
from django.core.exceptions import ValidationError
from .storage_usage import ensure_storage_capacity, StorageQuotaExceeded
from .slicer_approval import approve_profiles_for_worker
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


def _job_source_ids(job):
    """Owner-scoped list and detail lookups must use identical source IDs."""
    source_ids = {str(job.input_asset_id)}
    source_ids.update(str(item.get("asset_id")) for item in
                      (job.settings or {}).get("plate_objects", []) if isinstance(item, dict))
    for project_plate in (job.settings or {}).get("plates", []):
        if isinstance(project_plate, dict):
            source_ids.update(str(row.get("asset_id")) for row in
                              project_plate.get("objects", []) if isinstance(row, dict))
    return source_ids


def serialise(job, installed=None, temp_assets=None, *, list_view=False):
    # The batch lookup is only used for the authenticated user's list view.
    # The single-job endpoint retains its owner-scoped database lookup.
    source_ids = _job_source_ids(job)
    temporary_rows = (
        [temp_assets[asset_id] for asset_id in source_ids if asset_id in temp_assets]
        if temp_assets is not None
        else FileAsset.objects.filter(owner_id=job.owner_id, pk__in=source_ids,
                                      metadata__slicer_temporary=True)
    )
    temporary_inputs = [{
        "id": str(asset.pk), "name": asset.name,
        "filename": str((asset.metadata or {}).get("original_name") or asset.name),
        "category": "mesh", "url": asset.file.url if asset.file else "",
    } for asset in temporary_rows]
    can_slice = False
    if (job.status == "draft" and installed
            and not (job.settings or {}).get("plate_conflicts")):
        if list_view:
            # The list is refreshed on every active-job poll and may contain
            # 100 drafts. Full validation includes paint asset expansion,
            # imported profile inheritance and printer capability checks.
            # The start endpoint independently validates under a row lock.
            can_slice = True
        else:
            try:
                can_slice = validate_scheduling(job, installed)
            except (SlicerExecutionError, ValueError):
                pass
    return {
        "id": str(job.id),
        "status": job.status,
        "can_slice": can_slice,
        "progress": job.progress,
        "gcode_in_library": bool(job.output_asset_id and job.output_asset.category == "gcode"),
        "engine": job.engine,
        "engine_version": job.engine_version,
        "printer_preset": job.printer_preset,
        "filament_preset": job.filament_preset,
        "process_preset": job.process_preset,
        "nozzle_mm": str(job.nozzle_mm),
        "plate": job.plate,
        "settings": job.settings,
        "temporary_inputs": temporary_inputs,
        "printer_profile_id": str(job.printer_profile_id) if job.printer_profile_id else None,
        "filament_profile_id": str(job.filament_profile_id) if job.filament_profile_id else None,
        "process_profile_id": str(job.process_profile_id) if job.process_profile_id else None,
        "input_asset": {
            "id": str(job.input_asset_id),
            "name": job.input_asset.name,
            "filename": str((job.input_asset.metadata or {}).get("original_name")
                            or job.input_asset.name),
            # Only the authenticated owner can list this job or its source.
            # Use the same private URL convention as temporary_inputs.
            "url": job.input_asset.file.url if job.input_asset.file else "",
        },
        "printer": {"id": str(job.printer_id), "name": job.printer.name},
        "spool": {"id": str(job.spool_id), "name": job.spool.spool_id} if job.spool_id else None,
        "output_asset_id": str(job.output_asset_id) if job.output_asset_id else None,
        "output_asset": {
            "id": str(job.output_asset.pk),
            "name": job.output_asset.name,
            "filename": (job.output_asset.metadata or {}).get("original_name") or job.output_asset.name,
            # Only the slice owner sees these test eligibility facts. Merely
            # receiving them does not authorise a print-start operation.
            "creality_test_sha256": job.output_asset.sha256
                if (job.engine == "crealityprint"
                    and (job.output_asset.metadata or {}).get("multi_material_test") is True
                    and (job.output_asset.metadata or {}).get("printer_submission_verified") is False)
                else None,
            "size_bytes": job.output_asset.file.size if job.output_asset.file else None,
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


def _validate_project_name(name):
    if (not isinstance(name, str) or not 1 <= len(name.strip()) <= 80
            or any(ord(char) < 32 or ord(char) == 127 or char in '\\\\/:*?"<>|' for char in name)):
        raise ValueError("Project name must be 1–80 printable characters.")
    return name.strip()


def _validate_prime_tower_position(value):
    """Bounded XY preference for a plate, never executable profile content."""
    if value is None:
        return None
    if not isinstance(value, dict) or set(value) != {"x", "y"}:
        raise ValueError("Invalid prime tower position.")
    result = {}
    for axis in ("x", "y"):
        coordinate = value[axis]
        if (isinstance(coordinate, bool) or not isinstance(coordinate, (int, float))
                or not math.isfinite(coordinate) or not 0 <= coordinate <= 1000):
            raise ValueError("Prime tower coordinates must be finite millimetres within 0–1000.")
        result[axis] = round(float(coordinate), 3)
    return result


def _validate_independent_plate_volumes(raw, printable_ids=()):
    """Validate canonical non-printing plate objects, without an STL owner."""
    if not isinstance(raw, list) or len(raw) > MAX_TOTAL_MODIFIERS:
        raise ValueError("Independent plate volumes must be a bounded list.")
    volumes = []
    # The existing validator deliberately limits each storage batch to 12;
    # a plate can hold up to 48 independent regions across all models.
    for offset in range(0, len(raw), 12):
        volumes.extend(validate_modifier_volumes(raw[offset:offset + 12]))
    ids = [row["id"] for row in volumes]
    if len(set(ids)) != len(ids) or set(ids).intersection(printable_ids):
        raise ValueError("Independent plate volume IDs must be unique.")
    if any(row.get("coordinate_space") != "world" for row in volumes):
        raise ValueError("Independent plate volumes require world-space coordinates.")
    return volumes


def _draft_plate_settings(user, input_asset, settings):
    """Persist preview-only plate geometry; never compile it into slicer flags."""
    if settings is None:
        settings = {}
    if not isinstance(settings, dict) or set(settings) - {"plate_objects", "plate_label", "plates", "active_plate_id", "save_gcode_to_library", "workflow", "process_overrides", "flush_settings", "slot_filament_profiles", "material_tool_bindings", "material_topology", "multi_material_test", "creality_auto_arrange_offline", "prime_tower", "project_name", "plate_volumes", "prusa_native_tools"}:
        raise ValueError("Unsupported slicer plate settings.")
    prusa_native = settings.get("prusa_native_tools")
    if prusa_native is not None:
        from .slicer_prusa_tool_configuration import validate_prusa_native_tools
        prusa_native = validate_prusa_native_tools(prusa_native)
    prusa_native_field = ({"prusa_native_tools": prusa_native}
                          if prusa_native is not None else {})
    project_name = settings.get("project_name")
    name_field = {"project_name": _validate_project_name(project_name)} if project_name is not None else {}
    prime_tower = _validate_prime_tower_position(settings.get("prime_tower"))
    tower_field = {"prime_tower": prime_tower} if prime_tower is not None else {}
    process_overrides = validate_process_overrides(settings.get("process_overrides"))
    flush_settings = validate_flush_settings(settings.get("flush_settings"))
    # Independent per-bay filament presets are draft annotations only until
    # the engine's verified native tool routing is available. Never synthesize
    # a different tool/profile from a physical bay number.
    raw_slot_profiles = settings.get("slot_filament_profiles", [])
    if not isinstance(raw_slot_profiles, list) or len(raw_slot_profiles) > 16:
        raise ValueError("Invalid per-slot filament profile assignments.")
    slot_profiles, seen_slots = [], set()
    for entry in raw_slot_profiles:
        if not isinstance(entry, dict) or set(entry) != {"slot_id", "profile_id"}:
            raise ValueError("Invalid per-slot filament profile assignment.")
        slot_id = entry["slot_id"]
        if (not isinstance(slot_id, str) or not 1 <= len(slot_id) <= 128 or
                any(ord(char) < 33 or ord(char) > 126 for char in slot_id) or
                slot_id in seen_slots):
            raise ValueError("A filament slot must be a unique printable identifier.")
        profile_id = _uuid(entry["profile_id"])
        if not SlicerProfile.objects.filter(owner=user, pk=profile_id, kind="filament").exists():
            raise ValueError("Per-slot filament preset must be owned and imported.")
        seen_slots.add(slot_id)
        slot_profiles.append({"slot_id":slot_id,"profile_id":str(profile_id)})
    slot_fields = {"slot_filament_profiles":slot_profiles} if slot_profiles else {}
    # Explicit physical bay -> native tool mapping, never inferred from slot
    # order. Persisted for multi-material preflight only; physical printer
    # changeover remains a separate gated capability.
    raw_bindings = settings.get("material_tool_bindings", [])
    if not isinstance(raw_bindings, list) or len(raw_bindings) > 16:
        raise ValueError("Invalid native tool binding list.")
    bindings, used_slots, used_tools = [], set(), set()
    for entry in raw_bindings:
        if not isinstance(entry, dict) or set(entry) != {"slot_id", "tool_index"}:
            raise ValueError("Invalid native tool binding.")
        slot_id, tool = entry["slot_id"], entry["tool_index"]
        if (not isinstance(slot_id, str) or not 1 <= len(slot_id) <= 128 or
                any(ord(ch) < 33 or ord(ch) > 126 for ch in slot_id)
                or slot_id in used_slots or isinstance(tool, bool)
                or not isinstance(tool, int) or not 0 <= tool <= 15 or tool in used_tools):
            raise ValueError("Slot and logical tool assignments must be unique and bounded.")
        used_slots.add(slot_id)
        used_tools.add(tool)
        bindings.append({"slot_id": slot_id, "tool_index": tool})
    topology = settings.get("material_topology")
    if topology is not None and topology not in {
        "single_nozzle_changer", "independent_toolheads", "toolchanger",
        "idex", "manual_filament_change",
    }:
        raise ValueError("Unsupported material changeover topology.")
    routing_fields = {
        **({"material_tool_bindings": bindings} if bindings else {}),
        **({"material_topology": topology} if topology is not None else {}),
    }
    workflow = settings.get("workflow", "interactive")
    if not isinstance(workflow, str) or workflow not in {"setup", "quick", "interactive"}:
        raise ValueError("Unknown slicer workflow.")
    multi_material_test = settings.get("multi_material_test", False)
    if not isinstance(multi_material_test, bool):
        raise ValueError("Multi-material test mode must be true or false.")
    creality_auto_arrange_offline = settings.get("creality_auto_arrange_offline", False)
    if not isinstance(creality_auto_arrange_offline, bool):
        raise ValueError("Creality offline auto-arrangement must be true or false.")
    if creality_auto_arrange_offline and not multi_material_test:
        raise ValueError("Creality offline auto-arrangement requires multi-material test mode.")
    save_to_library = settings.get("save_gcode_to_library", False)
    if not isinstance(save_to_library, bool):
        raise ValueError("G-code library preference must be true or false.")
    label = settings.get("plate_label", "Plate 1")
    if (not isinstance(label, str) or not 1 <= len(label.strip()) <= 64
            or any(ord(character) < 32 or ord(character) == 127 for character in label)):
        raise ValueError("Build plate label must be 1–64 printable characters.")
    label = label.strip()
    project = settings.get("plates")
    project_fields = {}
    if project is not None:
        if not isinstance(project, list) or not 1 <= len(project) <= 8:
            raise ValueError("A slicer project must contain 1–8 plates.")
        ids, validated, total = set(), [], 0
        raw_by_id = {}
        for plate in project:
            if (not isinstance(plate, dict) or not {"id", "name", "objects"}.issubset(plate)
                    or set(plate) - {"id", "name", "objects", "prime_tower", "volumes"}):
                raise ValueError("Invalid build plate entry.")
            plate_id, name, instances = plate["id"], plate["name"], plate["objects"]
            if (not isinstance(plate_id, str) or
                    not re.fullmatch(r"plate-[a-zA-Z0-9-]{1,80}", plate_id) or plate_id in ids):
                raise ValueError("Build plate IDs must be unique.")
            ids.add(plate_id)
            if (not isinstance(name, str) or not 1 <= len(name.strip()) <= 64 or
                    any(ord(c) < 32 or ord(c) == 127 for c in name)):
                raise ValueError("Build plate names must be 1–64 printable characters.")
            if not isinstance(instances, list) or len(instances) > 200:
                raise ValueError("Each plate must have at most 200 models.")
            total += len(instances)
            if total > 200:
                raise ValueError("A multi-plate draft supports at most 200 models in total.")
            raw_by_id[plate_id] = instances
            canonical = "volumes" in plate
            if canonical and any(isinstance(row, dict) and any(
                    volume.get("coordinate_space") == "world"
                    for volume in row.get("modifier_volumes", [])
                    if isinstance(volume, dict)) for row in instances):
                raise ValueError("World-space volumes must be stored independently of printable records.")
            checked_volumes = _validate_independent_plate_volumes(
                plate["volumes"],
                {str(_uuid(row["instance_id"])) for row in instances}
                if canonical and all(isinstance(row, dict) and "instance_id" in row
                                     for row in instances) else (),
            ) if canonical else []
            if instances:
                primary = FileAsset.objects.filter(
                    pk=_uuid(instances[0].get("asset_id")), owner=user, category="mesh"
                ).first() if isinstance(instances[0], dict) else None
                if not primary:
                    raise ValueError("A plate contains an unavailable STL asset.")
                checked = _draft_plate_settings(user, primary, {
                    "plate_objects": instances, "plate_label": name.strip()
                })
                instances = checked["plate_objects"]
            if canonical:
                local_volumes = [volume for model in instances
                                 for volume in model.get("modifier_volumes", [])]
                if len(checked_volumes) + len(local_volumes) > MAX_TOTAL_MODIFIERS:
                    raise ValueError("Too many printable-local and independent volumes on a build plate.")
                if set(volume["id"] for volume in checked_volumes).intersection(
                        volume["id"] for volume in local_volumes):
                    raise ValueError("Independent and model-local volume IDs must be unique.")
            position = _validate_prime_tower_position(plate.get("prime_tower"))
            validated.append({"id": plate_id, "name": name.strip(), "objects": instances,
                              **({"volumes": checked_volumes} if canonical else {}),
                              **({"prime_tower": position} if position is not None else {})})
        active_id = settings.get("active_plate_id")
        if active_id not in ids:
            raise ValueError("Choose an active build plate.")
        active = next(plate for plate in validated if plate["id"] == active_id)
        submitted = settings.get("plate_objects", [])
        canonical = "volumes" in active
        # The current native slicer still consumes a temporary model-local
        # adapter. Its source meshes and exact volumes must match the canonical
        # independent plate data; never slice a silently omitted cutter.
        if canonical:
            if not isinstance(submitted, list):
                raise ValueError("Invalid active model list.")
            stripped = []
            inline = []
            for row in submitted:
                if not isinstance(row, dict):
                    continue
                world = [volume for volume in row.get("modifier_volumes", [])
                         if isinstance(volume, dict) and volume.get("coordinate_space") == "world"]
                local = [volume for volume in row.get("modifier_volumes", [])
                         if not isinstance(volume, dict) or volume.get("coordinate_space") != "world"]
                inline.extend(world)
                model = {key: value for key, value in row.items() if key != "modifier_volumes"}
                if local:
                    model["modifier_volumes"] = local
                stripped.append(model)
            if len(stripped) != len(submitted) or raw_by_id[active_id] != stripped:
                raise ValueError("The active plate must match its submitted printable models.")
            canonical_volumes = active["volumes"]
            submitted_volumes = _validate_independent_plate_volumes(
                settings.get("plate_volumes", []),
                {str(_uuid(row["instance_id"])) for row in submitted},
            )
            if sorted(canonical_volumes, key=lambda row: row["id"]) != sorted(
                    submitted_volumes, key=lambda row: row["id"]):
                raise ValueError("Active independent volumes must match saved plate volumes.")
            # Draft saving must not depend on the temporary editor adapter's
            # 12-volume-per-printable capacity. A plate can contain 48
            # independent volumes, including unattached ones. The *slicing*
            # admission gate separately requires full canonical coverage.
            canonical_by_id = {volume["id"]: volume for volume in canonical_volumes}
            if (len({volume.get("id") for volume in inline}) != len(inline) or
                    any(canonical_by_id.get(volume.get("id")) != volume
                        for volume in inline)):
                raise ValueError("Inline region adapter differs from independent plate volume records.")
        elif raw_by_id[active_id] != submitted:
            raise ValueError("The active plate must match its submitted model list.")
        elif "plate_volumes" in settings:
            raise ValueError("A legacy active plate cannot silently omit separate volumes.")
        active_position = next((p.get("prime_tower") for p in validated if p["id"] == active_id), None)
        if active_position != prime_tower:
            raise ValueError("The active prime tower position must match its build plate.")
        project_fields = {"plates": validated, "active_plate_id": active_id,
                          **({"plate_volumes": active["volumes"]} if canonical else {})}
    elif "active_plate_id" in settings or "plate_volumes" in settings:
        raise ValueError("Independent plate volumes require a multi-plate project.")
    if "plate_objects" not in settings:
        return {"plate_label": label, "save_gcode_to_library": save_to_library,
                "workflow": workflow, "process_overrides": process_overrides,
            **({"multi_material_test": True} if multi_material_test else {}),
                **({"creality_auto_arrange_offline": True} if creality_auto_arrange_offline else {}),
                **({"flush_settings": flush_settings} if flush_settings is not None else {}), **name_field, **tower_field, **slot_fields, **routing_fields, **prusa_native_field, **project_fields}
    objects = settings["plate_objects"]
    if not isinstance(objects, list) or not 1 <= len(objects) <= 200:
        raise ValueError("The visual build plate supports up to 200 model instances.")
    seen = set()
    saved = []
    for original_item in objects:
        item = expand_painted_item(user, original_item)
        required = {"instance_id", "asset_id", "x_mm", "y_mm", "rotation_deg",
                    "scale_percent", "color"}
        if (not isinstance(item, dict) or not required.issubset(item)
                or set(item) - required - {"scale_xyz_percent", "process_overrides", "rotation_xyz_deg", "assembly_id", "z_mm", "text_model", "material_slot", "colour_paint", "support_paint", "seam_paint", "fuzzy_skin_paint", "variable_layer_profile", "paint_asset_id", "modifier_volumes"}):
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
        for key, bound in (("x_mm", 10000), ("y_mm", 10000), ("rotation_deg", 360), ("scale_percent", 400), ("z_mm", 1000)):
            raw = item.get(key, 0) if key == "z_mm" else item[key]
            if isinstance(raw, bool) or not isinstance(raw, (int, float)) or not math.isfinite(raw):
                raise ValueError("Plate coordinates must be finite numbers.")
            if key == "scale_percent" and not 5 <= raw <= bound:
                raise ValueError("Plate scale must be between 5% and 400%.")
            if key == "z_mm" and not 0 <= raw <= bound:
                raise ValueError("Model elevation must be between 0 and 1000 mm.")
            if key not in {"scale_percent", "z_mm"} and abs(raw) > bound:
                raise ValueError("Plate transform exceeds its allowed range.")
            values[key] = round(float(raw), 3)
        tilt = item.get("rotation_xyz_deg")
        if tilt is not None:
            if (not isinstance(tilt, list) or len(tilt) != 2 or
                    any(isinstance(v, bool) or not isinstance(v, (int, float)) or
                        not math.isfinite(v) or abs(v) > 360 for v in tilt)):
                raise ValueError("Model X/Y tilt must be two finite angles.")
            values["rotation_xyz_deg"] = [round(float(v), 3) for v in tilt]
        xyz = item.get("scale_xyz_percent")
        if xyz is not None:
            if (not isinstance(xyz, list) or len(xyz) != 3 or any(
                isinstance(v, bool) or not isinstance(v, (int, float)) or
                not math.isfinite(v) or not 5 <= v <= 400 for v in xyz
            )):
                raise ValueError("X, Y and Z scaling must each be between 5% and 400%.")
            values["scale_xyz_percent"] = [round(float(v), 3) for v in xyz]
        color = item["color"]
        if not isinstance(color, str) or not re.fullmatch(r"#[0-9a-fA-F]{6}", color):
            raise ValueError("Choose a six-digit colour for each model.")
        # Advisory mapping to a printer-loaded filament slot. This is stored
        # with the draft but must NOT be interpreted as a native slicer tool,
        # extruder assignment, or a trusted physical spool identity.
        material_slot = item.get("material_slot")
        material_fields = {}
        if material_slot is not None:
            if (not isinstance(material_slot, dict) or set(material_slot) !=
                    {"printer_id", "slot_id", "slot_index"}):
                raise ValueError("Invalid intended material slot.")
            mapped_printer = str(_uuid(material_slot["printer_id"]))
            slot_id = material_slot["slot_id"]
            slot_index = material_slot["slot_index"]
            if (not isinstance(slot_id, str) or not 1 <= len(slot_id) <= 128 or
                    any(ord(char) < 33 or ord(char) > 126 for char in slot_id) or
                    isinstance(slot_index, bool) or not isinstance(slot_index, int)
                    or not 0 <= slot_index <= 63):
                raise ValueError("Invalid intended material slot.")
            material_fields = {"material_slot": {
                "printer_id": mapped_printer,
                "slot_id": slot_id,
                "slot_index": slot_index,
            }}
        instance_overrides = validate_process_overrides(item.get("process_overrides"))
        native_modifiers = validate_modifier_volumes(item.get("modifier_volumes"))
        assembly_id = item.get("assembly_id")
        if assembly_id is not None and (not isinstance(assembly_id, str) or
                not re.fullmatch(r"assembly:[a-zA-Z0-9-]{8,64}", assembly_id)):
            raise ValueError("Invalid assembly identifier.")
        text_model = item.get("text_model")
        text_fields = {}
        if text_model is not None:
            if not isinstance(text_model, dict) or set(text_model) != {
                "text", "font", "width", "depth", "height",
                "rotation_x", "rotation_y", "rotation_z",
            }:
                raise ValueError("Invalid editable text model metadata.")
            text = text_model["text"]
            font = text_model["font"]
            if (not isinstance(text, str) or not 1 <= len(text) <= 128 or
                    any(ord(ch) < 32 or ord(ch) == 127 for ch in text) or
                    font not in {"block", "sans", "sans-bold", "optimer", "gentilis"}):
                raise ValueError("Invalid printable text or font.")
            numerical = {}
            for key, low, high in (
                ("width", .2, 500), ("depth", .2, 500), ("height", .2, 500),
                ("rotation_x", -360, 360), ("rotation_y", -360, 360),
                ("rotation_z", -360, 360),
            ):
                value = text_model[key]
                if (isinstance(value, bool) or not isinstance(value, (int, float))
                        or not math.isfinite(value) or not low <= value <= high):
                    raise ValueError("Invalid editable text dimensions.")
                numerical[key] = round(float(value), 3)
            text_fields = {"text_model": {"text": text, "font": font, **numerical}}
        paint_fields = {}
        if "colour_paint" in item:
            paint_fields["colour_paint"] = validate_colour_paint(item["colour_paint"])
        if "support_paint" in item:
            paint_fields["support_paint"] = validate_support_paint(item["support_paint"])
        for field, kind in (("seam_paint", "seam"), ("fuzzy_skin_paint", "fuzzy")):
            if field in item:
                paint_fields[field] = validate_semantic_paint(item[field], kind)
        if "variable_layer_profile" in item:
            paint_fields["variable_layer_profile"] = validate_variable_layer_profile(item["variable_layer_profile"])
        # Validate the untrusted referenced contents above, but keep only
        # its immutable ID in the job JSON. Existing inline drafts remain
        # supported without a migration.
        if "paint_asset_id" in original_item:
            paint_fields = {"paint_asset_id": str(_uuid(original_item["paint_asset_id"]))}
        saved.append({"instance_id": instance_id, "asset_id": str(asset_id),
                      **({"assembly_id": assembly_id} if assembly_id is not None else {}),
                      **values, "color": color.lower(), **text_fields, **material_fields, **paint_fields,
                      **({"process_overrides": instance_overrides} if instance_overrides else {}),
                      **({"modifier_volumes": native_modifiers} if native_modifiers else {})})
    if sum(len(row.get("modifier_volumes", ())) for row in saved) > MAX_TOTAL_MODIFIERS:
        raise ValueError("Too many native modifiers on the build plate.")
    # The editor uses a single selection namespace for printable instances and
    # independent volumes. Reject collisions across storage owners as well as
    # collisions with printable IDs before saving or slicing a plate.
    volume_ids = [volume["id"] for row in saved
                  for volume in row.get("modifier_volumes", ())]
    if len(set(volume_ids)) != len(volume_ids) or seen.intersection(volume_ids):
        raise ValueError("Plate model and volume instance IDs must be unique.")
    if saved[0]["asset_id"] != str(input_asset.pk):
        raise ValueError("The first plate model must match the selected primary STL.")
    return {"plate_objects": saved, "plate_label": label, "save_gcode_to_library": save_to_library,
            "workflow": workflow, "process_overrides": process_overrides,
            **({"multi_material_test": True} if multi_material_test else {}),
                **({"creality_auto_arrange_offline": True} if creality_auto_arrange_offline else {}),
            **({"flush_settings": flush_settings} if flush_settings is not None else {}),
            **name_field, **tower_field, **slot_fields, **routing_fields, **prusa_native_field, **project_fields}


def _draft(user, data):
    # The HTTP boundary already limits compressed wire bytes and expanded JSON
    # to MAX_SLICER_JSON_BYTES. Keep the same bound for internal callers, not
    # the obsolete 128 KiB cap which rejected valid support-paint projects.
    if not isinstance(data, dict):
        raise ValueError("Slice configuration must be a JSON object.")
    if len(json.dumps(data, ensure_ascii=False, separators=(",", ":")).encode("utf-8")) > slicer_configuration_limits()[1]:
        raise ValueError("Slice configuration exceeds available expanded request memory.")
    allowed = {"engine", "engine_version", "input_asset_id", "printer_id", "spool_id", "printer_preset", "filament_preset", "process_preset", "nozzle_mm", "plate", "settings", "printer_profile_id", "filament_profile_id", "process_profile_id"}
    if set(data) - allowed:
        raise ValueError("Unknown slicing configuration fields.")
    engine = get_engine(data.get("engine"))
    version = _preset(data, "engine_version", 80)
    # The visual build plate is authoritative. Its first owned STL is the
    # primary asset stored on SliceJob for existing library/job integrations.
    plate_objects = (data.get("settings") or {}).get("plate_objects") if isinstance(data.get("settings", {}), dict) else None
    primary_id = plate_objects[0].get("asset_id") if (
        isinstance(plate_objects, list) and plate_objects and isinstance(plate_objects[0], dict)
    ) else data.get("input_asset_id")
    if data.get("input_asset_id") and plate_objects and str(data["input_asset_id"]) != str(primary_id):
        raise ValueError("The first plate model must match the selected primary STL.")
    input_asset = FileAsset.objects.filter(pk=_uuid(primary_id), owner=user).first()
    if not input_asset or input_asset.category not in {"mesh", "slicer"}:
        raise ValueError("The selected STL is no longer available in your private slicing workspace. Re-import the model to continue; no slicing job was started.")
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
    if settings_data.get("prusa_native_tools") is not None and (
            engine.key != "prusaslicer" or version != "2.9.7"):
        raise ValueError("Virtual native tools are supported only by PrusaSlicer 2.9.7.")
    plate_models = settings_data.get("plate_objects") or []
    if len(plate_models) > 1:
        # An inert draft may keep conflicting objects for editing. Record a
        # server-derived status so "Slice now" isn't advertised as available.
        # Actual scheduling independently re-checks geometry and ownership.
        from .slicer_plate_validation import validate_plate_collisions
        from .slicer_execution import _read_owned_file, MAX_INPUT
        try:
            owned = {str(asset.pk): asset for asset in FileAsset.objects.filter(
                owner=user, category="mesh",
                pk__in=[item["asset_id"] for item in plate_models])}
            validate_plate_collisions([(
                item, _read_owned_file(owned[str(item["asset_id"])],
                                       user.pk, input_model_budget(), "Draft STL")
            ) for item in plate_models])
        except (KeyError, ValueError, OSError):
            settings_data["plate_conflicts"] = True
    for assigned in settings_data.get("slot_filament_profiles", []):
        if not SlicerProfile.objects.filter(
                owner=user, pk=assigned["profile_id"], kind="filament",
                engine=engine.key, engine_version=version).exists():
            raise ValueError("Per-slot filament profile does not match the current engine and version.")
    # For one logical material on the active plate, the explicitly selected
    # slot's native filament profile is authoritative; file integrity and
    # inheritance are checked before execution without manual approval. Keep slot IDs
    # separate from logical tool indices and never guess a feeder mapping.
    assigned_slots = [
        item.get("material_slot", {}).get("slot_id")
        for item in plate_models if isinstance(item.get("material_slot"), dict)
    ]
    if (plate_models and len(assigned_slots) == len(plate_models)
            and len(set(assigned_slots)) == 1):
        slot_id = assigned_slots[0]
        matching = [
            row for row in settings_data.get("slot_filament_profiles", [])
            if row["slot_id"] == slot_id
        ]
        if len(matching) == 1:
            chosen = SlicerProfile.objects.filter(
                owner=user, pk=matching[0]["profile_id"], kind="filament",
                engine=engine.key, engine_version=version,
            ).first()
            if not chosen:
                raise ValueError("Assigned filament slot has no matching native profile.")
            data = {**data, "filament_profile_id": str(chosen.pk),
                    "filament_preset": chosen.name}
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

    plate_type = _preset(data, "plate", 80) if "plate" in data else "default"
    if engine.key in ("orcaslicer", "crealityprint", "bambustudio"):
        if plate_type not in ORCA_PLATES:
            raise ValueError("Choose a supported native build plate type.")
        if engine.key in ("crealityprint", "bambustudio") and plate_type != "default":
            printer_profile = native_profiles.get("printer_profile")
            if not printer_profile:
                raise ValueError("Select a native printer profile before choosing a plate.")
            try:
                supported = inspect_engine_plates(printer_profile)["supported"]
            except (SlicerProfileError, ValueError, TypeError, OSError) as exc:
                raise ValueError("Native build plate capabilities could not be verified.") from exc
            if plate_type not in supported:
                raise ValueError("Build plate is not supported by the selected printer profile.")
    elif plate_type != "default":
        raise ValueError("Build plate overrides are not supported by this slicer engine.")
    return SliceJob.objects.create(
        owner=user, input_asset=input_asset, printer=printer, spool=spool,
        **native_profiles,
        engine=engine.key, engine_version=version,
        **native_labels,
        nozzle_mm=nozzle, plate=plate_type,
        status="draft", settings=settings_data,
    )


@login_required
@require_http_methods(["POST"])
def upload_temporary_mesh(request):
    """Store an owner-private job source, not a user-visible Files entry.

    This remains available for saved drafts and the isolated worker, and is
    removed when its last draft is deleted. No model-library registration.
    """
    if not request.user.has_perm("core.add_fileasset"):
        return _error("You do not have permission to prepare slicing inputs.", 403)
    uploaded = request.FILES.get("file")
    if not uploaded:
        return _error("Choose an STL to slice.")
    filename = Path(str(uploaded.name or "")).name
    size = getattr(uploaded, "size", 0)
    if not filename.lower().endswith(".stl") or not 0 < size <= input_model_budget():
        return _error("Choose a nonempty STL no larger than 32 MiB.")
    try:
        ensure_storage_capacity(request.user, size)
        data = uploaded.read(input_model_budget() + 1)
        inspect_stl(data)
    except StorageQuotaExceeded:
        return _error("Insufficient private storage for a temporary slicing input.", 413)
    except (MeshInspectionError, ValueError) as exc:
        return _error(str(exc))
    asset = FileAsset(
        owner=request.user, category="mesh", name=filename,
        sha256=hashlib.sha256(data).hexdigest(),
        metadata={
            "extension": ".stl", "original_name": filename,
            "size_bytes": len(data), "slicer_temporary": True,
            "uploaded_from": "slicer",
        },
    )
    try:
        asset.file.save(filename, ContentFile(data), save=False)
        asset.full_clean()
        asset.save()
    except (ValidationError, OSError, ValueError) as exc:
        if asset.file:
            asset.file.delete(save=False)
        return _error("Could not store private slicing input: " + str(exc))
    return JsonResponse({"asset_id": str(asset.pk), "name": filename,
                         "temporary": True}, status=201)


def _cleanup_temporary_job_sources(job):
    """Retain private STL imports after a draft/job is removed.

    The same temporary STL can still be on a browser's live visual plate,
    even though no surviving SliceJob references it. There is no reliable
    server-side reference count for unsaved browser plate sessions, so
    removing an inactive slice job must not delete the input asset.
    Explicit file deletion or a future session-aware expiry policy can
    reclaim temporary storage without breaking the active editor.
    """
    return None


@login_required
@require_http_methods(["POST"])
def import_project_3mf(request):
    """Restore an exported MakerVault 3MF into owner-private temporary STLs."""
    if not request.user.has_perm("core.add_fileasset"):
        return _error("You do not have permission to import project models.", 403)
    uploaded = request.FILES.get("file")
    if not uploaded or not str(uploaded.name or "").lower().endswith(".3mf"):
        return _error("Choose a MakerVault .3mf project.")
    archive_budget = project_archive_budget()
    if uploaded.size <= 0 or uploaded.size > archive_budget:
        return _error("Project archive exceeds the available preparation memory.", 413)
    try:
        from .slicer_execution import MAX_INPUT
        stream = io.BytesIO(uploaded.read(archive_budget + 1))
        with zipfile.ZipFile(stream) as archive:
            infos = archive.infolist()
            if (len(infos) > 480 or len({info.filename for info in infos}) != len(infos)
                    or sum(info.file_size for info in infos)
                    > xml_geometry_budget() or
                    any(info.flag_bits & 1 for info in infos)):
                raise ValueError("Project archive exceeds safe limits.")
            manifest_info = archive.getinfo("Metadata/makervault-project.json")
            if manifest_info.file_size > 131072:
                raise ValueError("Project metadata is too large.")
            metadata = json.loads(archive.read(manifest_info).decode("utf-8"))
            if not isinstance(metadata, dict) or metadata.get("format") != "makervault-project-v1":
                raise ValueError("This is not a MakerVault project 3MF.")
            if "project_name" in metadata:
                _validate_project_name(metadata["project_name"])
            plates = metadata.get("plates")
            if not isinstance(plates, list) or not 1 <= len(plates) <= 8:
                raise ValueError("Invalid project plate list.")
            # Hydrate optional v2 painting sidecars before normal draft
            # validation. A sidecar never changes printable STL geometry.
            seen_paint_files = set()
            sidecar_bytes = 0
            for plate in plates:
                if not isinstance(plate, dict) or not isinstance(plate.get("objects"), list):
                    raise ValueError("Invalid project models.")
                for row in plate["objects"]:
                    if not isinstance(row, dict):
                        raise ValueError("Invalid project model.")
                    filename = row.pop("paint_sidecar", None)
                    if filename is None:
                        continue
                    if ("colour_paint" in row or not isinstance(filename, str) or
                            not re.fullmatch(r"Metadata/paint/paint-[0-9]{4}\.json", filename) or
                            filename in seen_paint_files):
                        raise ValueError("Invalid project paint sidecar.")
                    seen_paint_files.add(filename)
                    info = archive.getinfo(filename)
                    if not 0 < info.file_size <= 16 * 1024 * 1024:
                        raise ValueError("Project paint sidecar exceeds safe limits.")
                    sidecar_bytes += info.file_size
                    if sidecar_bytes > 64 * 1024 * 1024:
                        raise ValueError("Project painting regions exceed safe limits.")
                    value = json.loads(archive.read(info).decode("utf-8"))
                    if not isinstance(value, dict) or value.get("version") != 2:
                        raise ValueError("Project sidecar is not v2 painting data.")
                    row["colour_paint"] = validate_colour_paint(value)
                for row in plate["objects"]:
                    support_filename = row.pop("support_sidecar", None)
                    if support_filename is None:
                        continue
                    if ("support_paint" in row or not isinstance(support_filename, str) or
                            not re.fullmatch(r"Metadata/paint/support-[0-9]{4}\.json", support_filename) or
                            support_filename in seen_paint_files):
                        raise ValueError("Invalid project support-paint sidecar.")
                    seen_paint_files.add(support_filename)
                    info = archive.getinfo(support_filename)
                    if not 0 < info.file_size <= 16 * 1024 * 1024:
                        raise ValueError("Project support-paint sidecar exceeds safe limits.")
                    sidecar_bytes += info.file_size
                    if sidecar_bytes > 64 * 1024 * 1024:
                        raise ValueError("Project painting regions exceed safe limits.")
                    value = json.loads(archive.read(info).decode("utf-8"))
                    row["support_paint"] = validate_support_paint(value)
                for row in plate["objects"]:
                    for field, prefix, kind in (
                        ("seam_paint", "seam", "seam"),
                        ("fuzzy_skin_paint", "fuzzy", "fuzzy"),
                    ):
                        native_file = row.pop(prefix + "_sidecar", None)
                        if native_file is None:
                            continue
                        if (field in row or not isinstance(native_file, str) or
                                not re.fullmatch(r"Metadata/paint/" + prefix + r"-[0-9]{4}\.json", native_file) or
                                native_file in seen_paint_files):
                            raise ValueError("Invalid project semantic paint sidecar.")
                        seen_paint_files.add(native_file)
                        info = archive.getinfo(native_file)
                        if not 0 < info.file_size <= 16 * 1024 * 1024:
                            raise ValueError("Project semantic paint sidecar exceeds safe limits.")
                        sidecar_bytes += info.file_size
                        if sidecar_bytes > 64 * 1024 * 1024:
                            raise ValueError("Project painting regions exceed safe limits.")
                        row[field] = validate_semantic_paint(
                            json.loads(archive.read(info).decode("utf-8")), kind)
            active_id = metadata.get("active_plate_id")
            ids, source_names, total = set(), set(), 0
            for plate in plates:
                if (not isinstance(plate, dict) or
                        not {"id", "name", "objects"}.issubset(plate) or
                        set(plate) - {"id", "name", "objects", "prime_tower", "volumes"}):
                    raise ValueError("Invalid project plate.")
                _validate_prime_tower_position(plate.get("prime_tower"))
                pid, name, objects = plate["id"], plate["name"], plate["objects"]
                if (not isinstance(pid, str) or not re.fullmatch(r"plate-[A-Za-z0-9-]{1,80}", pid)
                        or pid in ids):
                    raise ValueError("Invalid or duplicate plate identifier.")
                ids.add(pid)
                if (not isinstance(name, str) or not 1 <= len(name.strip()) <= 64
                        or any(ord(c)<32 or ord(c)==127 for c in name)):
                    raise ValueError("Invalid project plate name.")
                if not isinstance(objects, list):
                    raise ValueError("Invalid project models.")
                total += len(objects)
                if total > 200:
                    raise ValueError("Project contains too many models.")
                printable_ids = set()
                for row in objects:
                    if not isinstance(row, dict):
                        raise ValueError("Invalid project model.")
                    printable_ids.add(str(_uuid(row.get("instance_id"))))
                    asset_id = str(_uuid(row.get("asset_id")))
                    source_names.add(asset_id)
                if "volumes" in plate:
                    plate["volumes"] = _validate_independent_plate_volumes(
                        plate["volumes"], printable_ids)
                    if any(isinstance(volume, dict) and
                           volume.get("coordinate_space") == "world"
                           for row in objects for volume in row.get("modifier_volumes", [])
                           if isinstance(row, dict)):
                        raise ValueError("Independent world-space volumes must not also be embedded in project model records.")
            if active_id not in ids or not source_names:
                raise ValueError("Project has no usable active plate or models.")
            original = {}
            total_bytes = 0
            for old_id in source_names:
                file_name = "Metadata/sources/" + old_id + ".stl"
                info = archive.getinfo(file_name)
                if not 0 < info.file_size <= input_model_budget():
                    raise ValueError("Project source STL exceeds safe limits.")
                total_bytes += info.file_size
                if total_bytes > source_input_budget(upper_cap=input_model_budget()):
                    raise ValueError("Project source geometry exceeds available preparation memory.")
                raw = archive.read(info)
                inspect_stl(raw)
                original[old_id] = raw
        ensure_storage_capacity(request.user, total_bytes)
        created = []
        mapping = {}
        try:
            for old_id, raw in original.items():
                name = "project-" + old_id[:8] + ".stl"
                asset = FileAsset(
                    owner=request.user, category="mesh", name=name,
                    sha256=hashlib.sha256(raw).hexdigest(),
                    metadata={"extension":".stl","original_name":name,
                              "size_bytes":len(raw),"slicer_temporary":True,
                              "uploaded_from":"slicer-project"},
                )
                asset.file.save(name, ContentFile(raw), save=False)
                asset.full_clean()
                asset.save()
                created.append(asset)
                mapping[old_id] = str(asset.pk)
            restored = []
            for plate in plates:
                rows=[{**row,"asset_id":mapping[str(_uuid(row["asset_id"]))]}
                      for row in plate["objects"]]
                if rows:
                    checked=_draft_plate_settings(request.user,created[
                        list(mapping.values()).index(rows[0]["asset_id"])],{
                        "plate_label":plate["name"],"plate_objects":rows,
                    })
                    rows=checked["plate_objects"]
                restored.append({"id":plate["id"],"name":plate["name"],"objects":rows,
                                 **({"volumes": plate["volumes"]} if "volumes" in plate else {}),
                                 **({"prime_tower":plate["prime_tower"]} if plate.get("prime_tower") is not None else {})})
        except Exception:
            for asset in created:
                if asset.file:
                    asset.file.delete(save=False)
                asset.delete()
            raise
    except (ValueError, KeyError, zipfile.BadZipFile, UnicodeError,
            OSError, MeshInspectionError, ValidationError) as exc:
        return _error("Could not restore project: " + str(exc), 422)
    except StorageQuotaExceeded:
        return _error("Not enough private storage to import this project.", 413)
    files=[{"id":str(asset.pk),"name":asset.name,"filename":asset.name,
            "category":"mesh","url":asset.file.url} for asset in created]
    return JsonResponse({
        "plates":restored,"active_plate_id":active_id,
        "configuration":{
            "project_name":metadata.get("project_name"),
            "engine":metadata.get("engine"),"engine_version":metadata.get("engine_version"),
            "printer":metadata.get("printer"),"filament":metadata.get("filament"),
            "process":metadata.get("process"),"nozzle_mm":metadata.get("nozzle_mm"),
        },
        "files":files,
    },status=201)


@login_required
@require_http_methods(["GET"])
def export_native_multimaterial_3mf(request, job_id):
    """Export an Orca-compatible model/tool 3MF for OFFLINE inspection.

    This is never printer submission and does not allow queued multi-material
    execution. Each selected filament must already be a verified native profile.
    """
    from .slicer_native_material_palette import prepare_multimaterial_plate
    from .slicer_multimaterial_execution import plan_native_multimaterial
    from .slicer_material_routing import MaterialRoutingError
    from .slicer_execution import _read_owned_file, MAX_INPUT
    from .slicer_bed_dimensions import trusted_plate_dimensions

    job = SliceJob.objects.select_related("printer_profile", "filament_profile").filter(
        pk=job_id, owner=request.user, status="draft"
    ).first()
    if not job:
        return _error("Slicer draft not found.", 404)
    try:
        settings = expand_painted_settings(request.user, job.settings or {})
    except (ValueError, OSError):
        return _error("A private painting asset is missing or invalid.", 422)
    objects = settings.get("plate_objects") or []
    profile_rows = settings.get("slot_filament_profiles") or []
    if (job.engine != "orcaslicer" or not 1 <= len(objects) <= 12
            or not isinstance(profile_rows, list)):
        return _error("Choose a saved Orca draft with verified multi-filament assignments.", 409)
    if any(item.get("support_paint", {}).get("regions") for item in objects):
        return _error("Support painting needs verified native enforcer/blocker export before slicing.", 409)
    if any(item.get("seam_paint", {}).get("regions") for item in objects):
        return _error("Seam painting needs verified native enforcer/blocker export before slicing.", 409)
    if any(item.get("fuzzy_skin_paint", {}).get("regions") for item in objects):
        return _error("Fuzzy skin painting needs verified native fuzzy facet export before slicing.", 409)
    if any(item.get("variable_layer_profile", {}).get("bands") for item in objects):
        return _error("Variable layer heights need verified native Orca layer-profile export before slicing.", 409)
    if settings.get("flush_settings") is not None:
        return _error("Custom flushing settings require separate native validation.", 409)
    try:
        # Exactly the same owner-scoped palette and material topology
        # validation as the isolated offline slicing route. Single-model
        # painted 3MFs and multi-model parts share one audited mapper.
        topology, tool_bindings, profiles = plan_native_multimaterial(
            job, settings=settings)
        width, depth = trusted_plate_dimensions(job.printer_profile)
        source_models = []
        for item in objects:
            asset = FileAsset.objects.filter(
                pk=item["asset_id"], owner=request.user, category="mesh"
            ).first()
            if asset is None:
                raise MaterialRoutingError("A model asset is no longer available.")
            source_models.append((
                item, _read_owned_file(asset, request.user.pk, input_model_budget(), "Model STL")
            ))
        result = prepare_multimaterial_plate(
            source_models, bed_width=width, bed_depth=depth,
            printer_id=job.printer_id, owner_id=job.owner_id,
            engine=job.engine, engine_version=job.engine_version,
            topology=topology,
            tool_bindings=tool_bindings, native_filament_profiles=profiles,
        )
    except (MaterialRoutingError, ValueError, KeyError, TypeError,
            SlicerExecutionError, SlicerProfileError, OSError) as exc:
        # Only bounded validator error messages are returned; no source file content.
        return _error(str(exc), 409)
    response = HttpResponse(result["model_3mf"], content_type="model/3mf")
    response["Content-Disposition"] = 'attachment; filename="MakerVault-native-material-test.3mf"'
    response["X-Content-Type-Options"] = "nosniff"
    response["Cache-Control"] = "no-store"
    response["X-MakerVault-Printer-Submission-Verified"] = "false"
    return response


@login_required
@require_http_methods(["GET"])
def export_project_3mf(request, job_id):
    """Return a self-contained private 3MF project. Never send it to a printer."""
    job = SliceJob.objects.filter(pk=job_id, owner=request.user).select_related(
        "printer_profile").first()
    if not job:
        return _error("Slicer draft not found.", 404)
    try:
        settings = expand_painted_settings(request.user, job.settings or {})
    except (ValueError, OSError):
        return _error("A private painting asset is missing or invalid.", 422)
    plates = settings.get("plates") or [{
        "id": "plate-1",
        "name": settings.get("plate_label", "Plate 1"),
        "objects": settings.get("plate_objects", []),
    }]
    try:
        from .slicer_bed_dimensions import trusted_plate_dimensions
        from .slicer_execution import _read_owned_file, MAX_INPUT
        from .slicer_plate_3mf import build_makervault_project_3mf
        width, depth = trusted_plate_dimensions(job.printer_profile)
        ids = {str(item["asset_id"]) for plate in plates for item in plate["objects"]}
        owned = {str(asset.pk): asset for asset in FileAsset.objects.filter(
            owner=request.user, category="mesh", pk__in=ids)}
        if len(owned) != len(ids):
            raise ValueError("Some project STL assets are no longer available.")
        raw = {ident:_read_owned_file(asset, request.user.pk, input_model_budget(), "Project STL")
               for ident, asset in owned.items()}
        rows = [(plate["name"], [(item, raw[str(item["asset_id"])])
                 for item in plate["objects"]]) for plate in plates]
        config = {
            "format": "makervault-project-v1",
            "active_plate_id": settings.get("active_plate_id", plates[0]["id"]),
            "project_name": settings.get("project_name", "MakerVault project"),
            "plates": plates,
            "printer": {"id": str(job.printer_id),
                        "profile_id": str(job.printer_profile_id or ""),
                        "preset": job.printer_preset},
            "filament": {"profile_id": str(job.filament_profile_id or ""),
                         "preset": job.filament_preset,
                         "spool_id": str(job.spool_id or "")},
            "process": {"profile_id": str(job.process_profile_id or ""),
                        "preset": job.process_preset,
                        "overrides": settings.get("process_overrides", {})},
            "engine": job.engine, "engine_version": job.engine_version,
            "nozzle_mm": str(job.nozzle_mm),
            "build_volume_mm": [width, depth],
        }
        archive = build_makervault_project_3mf(rows, bed_width=width,
                                               bed_depth=depth, metadata=config)
    except (ValueError, OSError, SlicerProfileError, SlicerExecutionError) as exc:
        return _error(str(exc), 422)
    response = HttpResponse(archive, content_type="model/3mf")
    response["Content-Disposition"] = 'attachment; filename="MakerVault-project.3mf"'
    response["X-Content-Type-Options"] = "nosniff"
    return response


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
            raw = stream.read(input_model_budget() + 1)
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
        key = row["key"]
        # Advertise capability records for the *actual installed version*.
        # Previously this only populated Orca 2.4/2.5, so Creality 7.3
        # painting remained greyed out even though native_capabilities()
        # correctly returned test_only for that engine.
        versions = {"2.4.2", "2.5.0"} if key == "orcaslicer" else set()
        if key == "crealityprint":
            versions.add("7.3.1")
        if key in installed:
            version = installed[key].get("version")
            if isinstance(version, str) and version:
                versions.add(version)
            row.update({"available": True, "enabled": True, "status": "validated",
                        "installed_version": version})
        row["feature_capabilities"] = {
            "default": native_capabilities(key, ""),
            **{version: native_capabilities(key, version)
               for version in sorted(versions)},
        }
    return JsonResponse({
        "engines": rows,
        "worker_configured": bool(installed),
        "can_verify_profiles": request.user.is_superuser,
        # Deployment intent is distinct from a healthy, approved engine.
        # Never infer an installed container merely because code is present.
        "deployment_enabled": bool(os.environ.get("MAKERVAULT_SLICER_WORKER_URL")),
        "preview_enabled": request.user.is_superuser,
    })


@login_required
@require_http_methods(["POST"])
def approve_native_profiles(request):
    """Explicit superuser fixture verification. Importing never approves profiles."""
    if not request.user.is_superuser:
        return _error("Only an administrator can verify slicing profiles.", 403)
    if len(request.body) > 4096:
        return _error("Fixture approval request is too large.", 413)
    try:
        data = json.loads(request.body.decode("utf-8"))
        if not isinstance(data, dict) or set(data) != {"engine", "engine_version", "profiles"}:
            raise ValueError("Select one engine and three matching native profiles.")
        engine = get_engine(data["engine"]).key
        version = _preset(data, "engine_version", 80)
        result = approve_profiles_for_worker(
            owner=request.user, engine=engine, version=version,
            profile_ids=data["profiles"],
        )
    except (ValueError, KeyError, TypeError, UnicodeDecodeError, SlicerExecutionError) as exc:
        return _error(str(exc), 409)
    return JsonResponse({
        "verified": True, **result,
        "warning": "Fixture verified for this exact engine, image, binary and profile trio only. No print was started.",
    })


# Keep the existing 8 MiB on-wire request limit. Painted polygons can be
# losslessly compressed, but expansion remains bounded and is never trusted.
MAX_SLICER_REQUEST_BYTES = 8 * 1024 * 1024  # compatibility fallback
MAX_SLICER_JSON_BYTES = 48 * 1024 * 1024  # compatibility fallback


def slicer_configuration_limits():
    """Bound compressed and expanded configuration by currently available RAM."""
    wire = memory_budget(reserve_bytes=256 * 1024 * 1024, expansion_factor=10)
    expanded = memory_budget(reserve_bytes=256 * 1024 * 1024, expansion_factor=6)
    return (
        MAX_SLICER_REQUEST_BYTES if wire is None else wire,
        MAX_SLICER_JSON_BYTES if expanded is None else expanded,
    )


def _slicer_request_json(request):
    raw = request.body
    request_budget, json_budget = slicer_configuration_limits()
    if len(raw) > request_budget:
        raise ValueError("Slice configuration exceeds available request memory. Reduce painted patch detail or free memory.")
    encoding = request.headers.get("Content-Encoding", "").strip().lower()
    if encoding == "gzip":
        try:
            decoder = zlib.decompressobj(wbits=16 + zlib.MAX_WBITS)
            decoded = decoder.decompress(raw, json_budget + 1)
            if (len(decoded) > json_budget or decoder.unconsumed_tail
                    or not decoder.eof or decoder.unused_data):
                raise ValueError("Compressed slicing project exceeded the expanded safety limit.")
            decoded += decoder.flush(json_budget + 1 - len(decoded))
            if len(decoded) > json_budget:
                raise ValueError("Compressed slicing project exceeded the expanded safety limit.")
            raw = decoded
        except zlib.error:
            raise ValueError("Invalid compressed slicing configuration.") from None
    elif encoding:
        raise ValueError("Unsupported slicing request encoding.")
    if len(raw) > json_budget:
        raise ValueError("Slicing project exceeded the expanded safety limit.")
    return json.loads(raw.decode("utf-8"))


@login_required
@require_http_methods(["POST"])
def paint_assets(request):
    """Store versioned masks separately from STL geometry and slice jobs."""
    if not request.user.has_perm("core.add_fileasset"):
        return _error("You do not have permission to store slicing data.", 403)
    try:
        payload = _slicer_request_json(request)
        if not isinstance(payload, dict) or set(payload) != {"mesh_asset_id", "paint"}:
            raise ValueError("Expected an owned STL and a paint mask.")
        asset = store_paint(request.user, payload["mesh_asset_id"],
                            payload["paint"], quota_check=ensure_storage_capacity)
    except StorageQuotaExceeded:
        return _error("Insufficient private storage for painting.", 413)
    except (ValueError, TypeError, UnicodeDecodeError) as exc:
        return _error(str(exc))
    except (ValidationError, OSError):
        return _error("Could not store private painting.")
    return JsonResponse({"asset_id": str(asset.pk), "sha256": asset.sha256}, status=201)


@login_required
@require_http_methods(["GET"])
def paint_asset_detail(request, asset_id):
    """Restore an edit mask only for its owner and exact mesh identity."""
    try:
        mesh_id = request.GET.get("mesh_asset_id")
        paint = load_paint(request.user, asset_id, mesh_id)
    except (ValueError, TypeError, OSError):
        return _error("Painting unavailable for the selected STL.", 404)
    return JsonResponse({"paint": paint})


@login_required
@require_http_methods(["GET", "POST"])
def jobs(request):
    if request.method == "GET":
        installed = verified_installation()
        saved_jobs = list(_rows(request.user)[:100])
        # Avoid an owner lookup and an asset query for every saved job on
        # initial load and on the five-second active-job poll.
        all_source_ids = set().union(*(_job_source_ids(job) for job in saved_jobs)) if saved_jobs else set()
        temporary_assets = {
            str(asset.pk): asset
            for asset in FileAsset.objects.filter(
                owner=request.user, pk__in=all_source_ids,
                metadata__slicer_temporary=True
            )
        } if all_source_ids else {}
        return JsonResponse({
            "jobs": [serialise(job, installed, temp_assets=temporary_assets,
                               list_view=True) for job in saved_jobs],
            "worker_configured": bool(installed),
            "can_cancel": request.user.has_perm("core.change_slicejob"),
            "can_delete": request.user.has_perm("core.delete_slicejob"),
        })
    if not request.user.has_perm("core.add_fileasset"):
        return _error("You do not have permission to prepare slicing jobs.", 403)
    try:
        data = _slicer_request_json(request)
        job = _draft(request.user, data)
    except (ValueError, TypeError, UnicodeDecodeError) as exc:
        return _error(str(exc) if isinstance(exc, ValueError) else "Invalid slice configuration.")
    return JsonResponse({"job": serialise(job), "execution_available": False}, status=201)


@login_required
@require_http_methods(["GET", "DELETE"])
def job_detail(request, job_id):
    if request.method == "DELETE":
        # Hide other users' job identities even when the caller has no delete
        # permission. The definitive state check remains under the row lock.
        with transaction.atomic():
            job = _rows(request.user).select_for_update(of=("self",)).filter(pk=job_id).first()
            if not job:
                return _error("Slice job not found.", 404)
            if not request.user.has_perm("core.delete_slicejob"):
                return _error("You do not have permission to delete slicing jobs.", 403)
            if job.status not in {"draft", "failed", "cancelled", "stale", "completed"}:
                return _error("Active queued or running slicing jobs cannot be deleted. Cancel them first.", 409)
            job.delete()
            _cleanup_temporary_job_sources(job)
        return JsonResponse({"deleted": True})
    job = _rows(request.user).filter(pk=job_id).first()
    if not job:
        return _error("Slice job not found.", 404)
    installed = verified_installation()
    return JsonResponse({"job": serialise(job, installed), "execution_available": bool(installed)})


def _profile_summary(profile):
    return {
        "id": str(profile.pk), "engine": profile.engine,
        "engine_version": profile.engine_version, "kind": profile.kind,
        "name": profile.name, "status": profile.status, "is_default": profile.is_default,
        "file_asset_id": str(profile.file_asset_id),
        "content_sha256": profile.content_sha256,
        "provenance": profile.provenance,
        "source_scope": profile.source_scope,
    }


@login_required
@require_http_methods(["GET", "POST"])
def official_profiles(request):
    """Search/import native candidates from pinned official engine catalogues."""
    if request.method == "GET":
        selected = request.GET.get("engine", "orcaslicer")
        try:
            version = (request.GET["version"] if "version" in request.GET
                       else default_catalogue_version(selected))
            selected_release = resolve_official_release(selected, version)
        except OfficialProfileError as exc:
            return _error(str(exc))
        if request.GET.get("brands") == "1":
            if selected != "orcaslicer" or request.GET.get("vendor") != "OrcaFilamentLibrary":
                return _error("Filament brand browsing requires the official Orca library.")
            try:
                return JsonResponse({"brands": official_filament_brands(version), "engine_version": version})
            except OfficialProfileError as exc:
                return _error(str(exc))
        if request.GET.get("catalogues") == "1":
            try:
                native = get_engine(selected)
            except ValueError as exc:
                return _error(str(exc))
            sources = {
                "orcaslicer": (available_official_vendors, OFFICIAL_ORCA_REF),
                "crealityprint": (available_creality_vendors, OFFICIAL_CRE_REF),
                "bambustudio": (available_bambu_vendors, OFFICIAL_BAMBU_REF),
                "prusaslicer": (available_prusa_vendors, OFFICIAL_PRUSA_REF),
                "snapmakerorca": (available_snapmaker_vendors, OFFICIAL_SNAP_REF),
            }
            provider = sources.get(selected)
            return JsonResponse({
                "engine": selected,
                "vendors": (available_official_vendors(version) if selected == "orcaslicer" else provider[0]()) if provider else [],
                "versions": approved_catalogue_versions(selected),
                "selected_version": version,
                "source_engine_version": selected_release.version,
                "ref": selected_release.ref,
                "native_profile_format": native.profile_format,
                "manual_import_available": True,
                "official_search_available": bool(provider),
                "verified_for_execution": False,
            })
        if request.GET.get("models") == "1":
            model_catalogues = {"orcaslicer": orca_catalogue_models,
                                "crealityprint": creality_catalogue_models,
                                "bambustudio": bambu_catalogue_models,
                                "prusaslicer": prusa_catalogue_models,
                                "snapmakerorca": snapmaker_catalogue_models}
            provider = model_catalogues.get(selected)
            if not provider:
                return _error("This slicer has no official printer catalogue.")
            try:
                models = (orca_catalogue_models(request.GET.get("vendor", "Creality"))
                          if selected == "orcaslicer" and version == OFFICIAL_ORCA_VERSION else
                          orca_catalogue_models(request.GET.get("vendor", "Creality"), version)
                          if selected == "orcaslicer" else provider(request.GET.get(
                               "vendor", "PrusaResearch" if selected == "prusaslicer" else "Creality")))
            except OfficialProfileError as exc:
                return _error(str(exc), 400)
            return JsonResponse({"engine": selected, "models": models})
        # Bounded, one-based server-side pagination applies to all official
        # catalogues and preset kinds, including the large Prusa INI bundle.
        # An invalid page is rejected rather than scanning an unbounded offset.
        page_text = request.GET.get("page", "1")
        if not page_text.isdecimal() or len(page_text) > 6:
            return _error("Page must be a positive integer.")
        page = int(page_text)
        if not 1 <= page <= 10000:
            return _error("Page must be between 1 and 10000.")
        page_size = 40
        offset = (page - 1) * page_size
        searcher = {
            "orcaslicer": search_official_profiles,
            "crealityprint": search_creality_profiles,
            "bambustudio": search_bambu_native_profiles,
            "prusaslicer": search_prusa_profiles,
            "snapmakerorca": search_snapmaker_profiles,
        }.get(selected)
        if searcher is None:
            return _error("Official profile search is not available for this engine.")
        try:
            # Printer selection is resolved against the signed-in user's own
            # records; never trust an arbitrary client-provided machine name.
            printer_id = request.GET.get("printer_id")
            printer_model = None
            if printer_id:
                try:
                    printer_pk = _uuid(printer_id)
                except ValueError:
                    return _error("Invalid selected printer.")
                printer = Printer.objects.filter(
                    pk=printer_pk, owner=request.user, is_active=True
                ).first()
                if not printer:
                    return _error("Selected printer is not available to this account.", 404)
                printer_model = (printer.model or printer.name or "").strip()
            # Optional catalogue model overrides the default selected printer.
            # Resolve it from a pinned vendor manifest, not arbitrary client text.
            chosen_model = request.GET.get("model")
            if chosen_model:
                model_catalogues = {"orcaslicer": orca_catalogue_models,
                                    "crealityprint": creality_catalogue_models,
                                "bambustudio": bambu_catalogue_models,
                                "prusaslicer": prusa_catalogue_models,
                                "snapmakerorca": snapmaker_catalogue_models}
                catalogue_models = (orca_catalogue_models(request.GET.get("vendor", "Creality"))
                                    if selected == "orcaslicer" and version == OFFICIAL_ORCA_VERSION else
                                    orca_catalogue_models(request.GET.get("vendor", "Creality"), version)
                                    if selected == "orcaslicer" else
                                    model_catalogues[selected](request.GET.get(
                                         "vendor", "PrusaResearch" if selected == "prusaslicer" else "Creality")))
                if chosen_model not in catalogue_models:
                    return _error("Choose a printer model listed in the official catalogue.")
                printer_model = chosen_model
            args = (
                request.GET.get("q", ""),
                request.GET.get("kind", "printer"),
                request.GET.get("vendor", "PrusaResearch" if selected == "prusaslicer" else "Creality"),
            )
            slot_discovery = request.GET.get("slot_discovery") == "1"
            if slot_discovery and (selected != "orcaslicer" or not printer_id):
                return _error("Slot profile discovery requires OrcaSlicer and a selected printer.")
            material_query = request.GET.get("material", "")[:32]
            manufacturer_query = request.GET.get("manufacturer", "")[:80]
            page_kwargs = {"offset": offset} if offset else {}
            results = (search_official_profiles(*args, printer_model=printer_model, version=version,
                           brand=request.GET.get("brand", ""),
                           slot_discovery=slot_discovery, material=material_query,
                           manufacturer=manufacturer_query, **page_kwargs)
                       if selected == "orcaslicer" and
                          (slot_discovery or version != OFFICIAL_ORCA_VERSION or request.GET.get("brand")) else
                       searcher(*args, printer_model=printer_model, **page_kwargs) if printer_model else
                       searcher(*args, **page_kwargs))
            results["printer_model_filter"] = printer_model
            results["page"] = page
            results["page_size"] = page_size
            results["total_pages"] = max(1, (results.get("total_matches", 0) + page_size - 1) // page_size)
        except OfficialProfileError as exc:
            return _error(str(exc), 503 if "source" in str(exc).lower() or "contact" in str(exc).lower() else 400)
        return JsonResponse(results)
    if not request.user.has_perm("core.add_fileasset"):
        return _error("You do not have permission to import official native profiles.", 403)
    if len(request.body) > 4096:
        return _error("Official profile selection is too large.", 413)
    try:
        selection = json.loads(request.body.decode("utf-8"))
        if not isinstance(selection, dict) or set(selection) - {"engine", "vendor", "kind", "name", "sub_path", "engine_version"}:
            raise ValueError("Invalid official profile selection.")
        engine = selection.get("engine", "orcaslicer")
        providers = {
            "orcaslicer": (OFFICIAL_ORCA_VERSION, OFFICIAL_ORCA_SOURCE, OFFICIAL_ORCA_REF, fetch_official_profile),
            "crealityprint": (OFFICIAL_CRE_VERSION, OFFICIAL_CRE_SOURCE, OFFICIAL_CRE_REF, fetch_creality_profile),
            "bambustudio": (OFFICIAL_BAMBU_VERSION, OFFICIAL_BAMBU_SOURCE, OFFICIAL_BAMBU_REF, fetch_bambu_model),
            "prusaslicer": (OFFICIAL_PRUSA_VERSION, OFFICIAL_PRUSA_SOURCE, OFFICIAL_PRUSA_REF, fetch_prusa_profile),
            "snapmakerorca": (OFFICIAL_SNAP_VERSION, OFFICIAL_SNAP_SOURCE, OFFICIAL_SNAP_REF, fetch_snapmaker_profile),
        }
        if engine not in providers:
            return _error("Official import is not available for this engine.")
        version, source, ref, fetcher = providers[engine]
        selected_version = (selection["engine_version"] if "engine_version" in selection
                            else default_catalogue_version(engine))
        release = resolve_official_release(engine, selected_version)
        if (source != release.source
                or (ref != release.ref and engine != "orcaslicer")):
            raise ValueError("Official provider configuration differs from the reviewed release.")
        version, source, ref = release.version, release.source, release.ref
        kind = selection.get("kind")
        vendor = selection.get("vendor", "PrusaResearch" if engine == "prusaslicer" else "Creality")
        name = selection.get("name")
        subpath = selection.get("sub_path")
        if not isinstance(name, str) or len(name) > 200:
            raise ValueError("Invalid native profile name.")
        # Re-importing an already registered official preset is allowed to
        # restore missing parents in its verified upstream inheritance chain.
        # Existing records are never overwritten or implicitly modified.
        # Fetch and validate the complete bounded parent chain *before*
        # mutating the database. Never install a partial official preset.
        chain = (fetch_bambu_native_chain(kind, name, subpath, vendor, version=version)
                 if engine == "bambustudio" else
                 [(name, subpath, fetch_prusa_profile(kind, name, subpath, vendor))]
                 if engine == "prusaslicer" else
                 official_profile_chain(engine, kind, name, subpath, vendor, version=version))
        # Official source identity is pinned to an engine repository/tag and
        # catalogue vendor, not merely to a potentially reused preset name.
        source_scope = f"{source}@{ref}/{vendor}"
        if len(source_scope) > 200:
            raise ValueError("Official source scope is too long.")
        prepared = []
        for native_name, native_subpath, raw in chain:
            existing = SlicerProfile.objects.filter(
                owner=request.user, engine=engine,
                engine_version=version, kind=kind, name=native_name,
                source_scope=source_scope,
            ).first()
            if existing:
                # Different manufacturer catalogues can reuse a native parent
                # name with different contents. Never splice one vendor's
                # settings into another vendor's inheritance chain.
                import hashlib
                if existing.content_sha256 != hashlib.sha256(raw).hexdigest():
                    raise ValueError(
                        "An official native preset changed within the same pinned source: "
                        + native_name[:120] + ". Existing imported files were preserved; "
                        "review the conflicting upstream content before replacing anything."
                    )
                continue
            asset = FileAsset(
                owner=request.user, name=native_name + (".ini" if engine == "prusaslicer" else ".json"), category="source",
                metadata={"original_name": native_name + (".ini" if engine == "prusaslicer" else ".json"),
                          "extension": ".ini" if engine == "prusaslicer" else ".json",
                          "slicer_profile_internal": True},
            )
            asset.file = ContentFile(raw, name="official-" + engine + ("-model.ini" if engine == "prusaslicer" else "-profile.json"))
            inspected = inspect_native_profile(asset, engine)
            provenance = f"{source}@{ref}/{vendor}/{native_subpath}"
            if len(provenance) > 200:
                raise ValueError("Official source identity is too long.")
            prepared.append((native_name, asset, inspected["sha256"], provenance))
        with transaction.atomic():
            created_names = []
            for native_name, asset, digest, provenance in prepared:
                asset.save()
                SlicerProfile.objects.create(
                    owner=request.user, file_asset=asset, engine=engine,
                    engine_version=version, kind=kind, name=native_name,
                    provenance=provenance, source_scope=source_scope,
                    content_sha256=digest, status="candidate",
                )
                created_names.append(native_name)
            profile = SlicerProfile.objects.get(
                owner=request.user, engine=engine,
                engine_version=version, kind=kind, name=name,
                source_scope=source_scope,
            )
            # Reusing an existing, byte-identical native preset is idempotent.
            # The UI still needs its ID to attach it to the selected CFS/AMS slot.
    except (OfficialProfileError, ValueError, TypeError, UnicodeDecodeError, SlicerProfileError) as exc:
        return _error(str(exc))
    except IntegrityError:
        return _error("The selected official profile is already registered.", 409)
    return JsonResponse({
        "profile": _profile_summary(profile), "engine_version": version,
        "imported_profiles": created_names, "parent_chain_length": len(chain),
        "execution_available": False,
        "warning": "Official profile and available parent chain imported as unverified candidates. A real engine fixture is still required.",
    }, status=201 if created_names else 200)


def _native_parent_ids(rows):
    """Find managed dependency presets referenced by another native profile.

    Only a verified source hash can declare a dependency. Malformed sources
    are left visible for manual inspection, never treated as a valid parent.
    """
    # Reading hundreds of native JSON files at every slicer entry was
    # dominating profile-list latency. Cached results are keyed by the user's
    # exact imported profile identities and content hashes. Changing any
    # registered parent/child profile automatically produces a different key.
    fingerprint = json.dumps(sorted((
        str(row.pk), str(row.owner_id), row.engine, row.engine_version,
        row.kind, row.name, row.source_scope, row.content_sha256,
        str(row.file_asset_id)
    ) for row in rows), separators=(",", ":"), ensure_ascii=False)
    cache_key = "slicer-profile-parents-v2:" + hashlib.sha256(fingerprint.encode()).hexdigest()
    cached = cache.get(cache_key)
    if isinstance(cached, list):
        return {uuid.UUID(identifier) for identifier in cached}
    by_identity = {(row.owner_id, row.engine, row.engine_version,
                    row.kind, row.name, row.source_scope): row.pk for row in rows}
    parent_ids = set()
    for row in rows:
        if row.engine not in {"orcaslicer", "crealityprint"}:
            continue
        try:
            with row.file_asset.file.open("rb") as stream:
                raw = stream.read(1024 * 1024 + 1)
            if not raw or len(raw) > 1024 * 1024:
                continue
            if hashlib.sha256(raw).hexdigest() != row.content_sha256:
                continue
            source = json.loads(raw.decode("utf-8-sig"))
            if not isinstance(source, dict):
                continue
            parent = source.get("inherits")
            if isinstance(parent, str):
                identity = (row.owner_id, row.engine, row.engine_version,
                            row.kind, parent, row.source_scope)
                found = by_identity.get(identity)
                if found:
                    parent_ids.add(found)
        except (OSError, ValueError, UnicodeError, AttributeError):
            continue
    cache.set(cache_key, [str(identifier) for identifier in parent_ids], timeout=300)
    return parent_ids


@login_required
@require_http_methods(["GET", "POST"])
def profiles(request):
    if request.method == "GET":
        rows = list(SlicerProfile.objects.filter(owner=request.user).select_related(
            "file_asset"
        ).order_by("engine", "kind", "name")[:500])
        parent_ids = _native_parent_ids(rows)
        return JsonResponse({"profiles": [
            {**_profile_summary(row), "is_dependency": row.pk in parent_ids}
            for row in rows
        ]})

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
@require_http_methods(["GET", "POST"])
def customise_profile(request, profile_id):
    """Clone a native JSON preset, applying only bounded GUI-supported changes."""
    profile = SlicerProfile.objects.filter(
        pk=profile_id, owner=request.user, engine__in=["orcaslicer", "crealityprint", "bambustudio"]
    ).select_related("file_asset").first()
    if not profile:
        return _error("An owned native slicing profile is required.", 404)
    if profile.kind not in EDITABLE_PROFILE_SETTINGS:
        return _error("Unsupported native profile type.")
    if request.method == "GET":
        current = {}
        available = {}
        try:
            raw = resolved_native_profile(profile)
            properties = json.loads(raw.decode("utf-8-sig"))
            if not isinstance(properties, dict):
                raise ValueError("Unsupported native profile.")
            for key, limits in EDITABLE_PROFILE_SETTINGS[profile.kind].items():
                if key not in properties:
                    continue
                value = properties.get(key)
                if isinstance(value, list):
                    # This simple editor works on one native value only.
                    # Never imply that it can safely edit independent extruders.
                    if len(value) != 1:
                        continue
                    value = value[0]
                try:
                    numeric = float(value.removesuffix("%") if isinstance(value, str) else value)
                except (ValueError, TypeError):
                    continue
                if math.isfinite(numeric):
                    available[key] = limits
                    current[key] = numeric
        except (OSError, ValueError, UnicodeDecodeError):
            return _error("Cannot inspect original native profile.", 422)
        return JsonResponse({
            "profile": _profile_summary(profile),
            "settings": {name: {"min": limits[0], "max": limits[1],
                               "current": current.get(name),
                               "outside_editor_bounds": not (limits[0] <= current[name] <= limits[1])}
                         for name, limits in available.items()},
            "warning": "Custom presets are unverified; original native preset is preserved.",
        })
    try:
        dependent = _profile_children(profile)
    except SlicerProfileError as exc:
        return _error(str(exc), 409)
    if dependent:
        return _error("This preset is a native dependency for other profiles. "
                      "Customise a complete printer, filament or process preset instead.", 409)
    if not request.user.has_perm("core.add_fileasset"):
        return _error("You do not have permission to create custom profiles.", 403)
    if len(request.body) > 4096:
        return _error("Profile update exceeds the allowed size.", 413)
    try:
        data = json.loads(request.body.decode("utf-8"))
        if not isinstance(data, dict) or set(data) != {"name", "settings"}:
            raise ValueError("A custom profile name and supported settings are required.")
        name = _preset(data, "name")
        if SlicerProfile.objects.filter(
            owner=request.user, engine=profile.engine,
            engine_version=profile.engine_version, kind=profile.kind, name=name
        ).exists():
            return _error("Choose a unique name for the custom profile.", 409)
        # Start from the fully inherited, hash-validated native profile.
        # The new custom profile is flattened and has no 'inherits' link,
        # so it remains usable even when imported parent records change.
        original = resolved_native_profile(profile)
        edited = customise_native_json(original, profile.kind, name, data["settings"])
        asset = FileAsset(
            owner=request.user, name=name + ".json", category="source",
            metadata={"original_name": name + ".json", "extension": ".json",
                      "slicer_custom_source_profile_id": str(profile.id),
                      "slicer_profile_internal": True},
        )
        asset.file = ContentFile(edited, name="custom-native-slicer-profile.json")
        inspected = inspect_native_profile(asset, profile.engine)
        with transaction.atomic():
            asset.save()
            custom = SlicerProfile.objects.create(
                owner=request.user, file_asset=asset, engine=profile.engine,
                engine_version=profile.engine_version, kind=profile.kind,
                name=name, provenance=("Custom copy of " + str(profile.id))[:200],
                content_sha256=inspected["sha256"], status="candidate",
            )
    except (ValueError, TypeError, UnicodeDecodeError, SlicerProfileError) as exc:
        return _error(str(exc))
    except (OSError, IntegrityError):
        return _error("Custom profile could not be saved. Check source and unique name.", 409)
    return JsonResponse({
        "profile": _profile_summary(custom),
        "execution_available": False,
        "warning": "Custom profile saved as an unverified candidate. Original preserved.",
    }, status=201)


@login_required
@require_http_methods(["POST"])
def save_process_profile(request, profile_id):
    """Save an interactive draft's safe native Orca/Creality process edits as a new native preset.

    The source profile is hash-verified and fully flattened; no active source
    file or existing SlicerProfile row is modified, and a candidate profile
    never receives verified execution status by being saved.
    """
    if not request.user.has_perm("core.add_fileasset"):
        return _error("You do not have permission to save custom profiles.", 403)
    profile = SlicerProfile.objects.filter(
        pk=profile_id, owner=request.user, engine__in=["orcaslicer", "crealityprint", "bambustudio", "prusaslicer"], kind="process"
    ).select_related("file_asset").first()
    if not profile:
        return _error("An owned native slicing process profile is required.", 404)
    if len(request.body) > 4096:
        return _error("Custom process profile request is too large.", 413)
    try:
        data = json.loads(request.body.decode("utf-8"))
        if not isinstance(data, dict) or set(data) != {"name", "settings"}:
            raise ValueError("A unique profile name and changed settings are required.")
        name = _preset(data, "name")
        edits = validate_process_overrides(data.get("settings"))
        if not edits:
            raise ValueError("Change at least one supported process setting first.")
        if SlicerProfile.objects.filter(
            owner=request.user, engine=profile.engine, engine_version=profile.engine_version,
            kind="process", name=name
        ).exists():
            return _error("A process profile with this name already exists.", 409)
        source = resolved_native_profile(profile)
        extension = ".ini" if profile.engine == "prusaslicer" else ".json"
        if profile.engine == "prusaslicer":
            from .slicer_prusa_process_settings import apply_prusa_process_overrides
            updated = apply_prusa_process_overrides(source, edits)
        else:
            updated = apply_process_overrides(source, edits)
            native = json.loads(updated.decode("utf-8-sig"))
            native["name"] = name
            updated = json.dumps(native, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        if len(updated) > 1024 * 1024:
            raise ValueError("Custom process profile exceeds the file size limit.")
        asset = FileAsset(
            owner=request.user, name=name + extension, category="source",
            metadata={"original_name": name + extension, "extension": extension,
                      "slicer_custom_source_profile_id": str(profile.pk),
                      "slicer_profile_internal": True},
        )
        asset.file = ContentFile(updated, name="custom-native-process-profile" + extension)
        inspected = inspect_native_profile(asset, profile.engine)
        with transaction.atomic():
            asset.save()
            custom = SlicerProfile.objects.create(
                owner=request.user, file_asset=asset, engine=profile.engine,
                engine_version=profile.engine_version, kind="process", name=name,
                provenance=("Custom copy of " + str(profile.pk))[:200],
                content_sha256=inspected["sha256"], status="candidate",
            )
    except (ValueError, TypeError, UnicodeDecodeError, SlicerProfileError) as exc:
        return _error(str(exc))
    except (OSError, IntegrityError):
        return _error("Could not save custom process profile. Check its name and settings.", 409)
    return JsonResponse({
        "profile": _profile_summary(custom), "execution_available": False,
        "warning": "Custom native process profile saved as an unverified candidate. Original preserved.",
    }, status=201)


@login_required
@require_http_methods(["POST"])
def set_default_profile(request, profile_id):
    """Opt-in default for exactly this user's native engine/version/kind."""
    profile = SlicerProfile.objects.filter(pk=profile_id, owner=request.user).first()
    if not profile:
        return _error("Native slicer profile not found.", 404)
    if not (request.user.has_perm("core.change_slicerprofile") or request.user.has_perm("core.add_fileasset")):
        return _error("You do not have permission to manage profile defaults.", 403)
    if len(request.body) > 128:
        return _error("Default profile request is too large.", 413)
    try:
        data = json.loads(request.body.decode("utf-8"))
        if not isinstance(data, dict) or set(data) != {"default"} or not isinstance(data["default"], bool):
            raise ValueError("Choose whether this profile is the default.")
        if data["default"]:
            try:
                dependent = _profile_children(profile)
            except SlicerProfileError as exc:
                return _error(str(exc), 409)
            if dependent:
                return _error("An inherited native parent cannot be the active default profile.", 409)
        # Lock the owner row to serialize updates even when two different
        # native profile records are set as default simultaneously.
        from django.contrib.auth import get_user_model
        with transaction.atomic():
            get_user_model().objects.select_for_update().get(pk=request.user.pk)
            related = SlicerProfile.objects.filter(
                owner=request.user, engine=profile.engine,
                engine_version=profile.engine_version, kind=profile.kind,
            )
            related.update(is_default=False)
            if data["default"]:
                related.filter(pk=profile.pk).update(is_default=True)
        profile.refresh_from_db()
    except (ValueError, TypeError, UnicodeDecodeError):
        return _error("Invalid default selection.")
    return JsonResponse({"profile": _profile_summary(profile), "default": profile.is_default})


def _profile_children(profile):
    """Find direct native children before deleting a parent registration.

    Native inheritance is by name, not a database foreign key. Restrict to
    the same account, engine, version and kind; fail closed on unreadable or
    modified candidate sources so deletion cannot silently break presets.
    """
    candidates = SlicerProfile.objects.filter(
        owner_id=profile.owner_id, engine=profile.engine,
        engine_version=profile.engine_version, kind=profile.kind,
    ).exclude(pk=profile.pk).select_related("file_asset")
    if candidates.count() > 1000:
        raise SlicerProfileError("Too many profiles to safely check parent dependencies.")
    children = []
    for child in candidates:
        try:
            with child.file_asset.file.open("rb") as source:
                raw = source.read(1024 * 1024 + 1)
            if not raw or len(raw) > 1024 * 1024:
                raise ValueError("Profile source length invalid")
            if hashlib.sha256(raw).hexdigest() != child.content_sha256:
                raise ValueError("Profile source changed")
            data = json.loads(raw.decode("utf-8-sig"))
            if not isinstance(data, dict):
                raise ValueError("Profile source is not JSON object")
        except (OSError, ValueError, UnicodeError, AttributeError):
            raise SlicerProfileError(
                "Cannot safely inspect all same-engine native profile dependencies."
            ) from None
        if data.get("inherits") == profile.name and child.source_scope == profile.source_scope:
            children.append(child.name)
    return children


@login_required
@require_http_methods(["DELETE"])
def delete_profile(request, profile_id):
    """Delete only this user's profile registration; preserve its source FileAsset.

    Slices retain immutable native-profile references. Protected records cannot
    be removed until their dependent jobs have been resolved separately.
    """
    # The owner who can import/manage their native presets must also be able
    # to remove their own unused registrations. The dedicated delete permission
    # remains supported for administrators; neither permission grants access to
    # another owner's profiles or bypasses native-parent/job safeguards.
    if not (request.user.has_perm("core.delete_slicerprofile")
            or request.user.has_perm("core.add_fileasset")):
        return _error("You do not have permission to remove slicer profiles.", 403)
    profile = SlicerProfile.objects.filter(pk=profile_id, owner=request.user).first()
    if profile is None:
        return _error("Slicer profile not found.", 404)
    try:
        children = _profile_children(profile)
    except SlicerProfileError as exc:
        return _error(str(exc) + " Profile was not deleted.", 409)
    if children:
        return _error(
            "This profile is a required native parent of " +
            ", ".join(children[:3]) +
            (" and other profiles" if len(children) > 3 else "") +
            ". Delete or replace its dependent profiles first; the parent was preserved.",
            409,
        )
    # Completed G-code does not need the original profile row forever.
    # SliceJob stores the original native preset names and engine version;
    # leave its completed result, output asset and history untouched.
    # Draft/queued/running/failed jobs remain protected until separately
    # resolved because they may be reopened or retried.
    with transaction.atomic():
        refs = SliceJob.objects.select_for_update().filter(owner=request.user)
        from django.db.models import Q
        linked = refs.filter(
            Q(printer_profile_id=profile.pk) |
            Q(filament_profile_id=profile.pk) |
            Q(process_profile_id=profile.pk))
        # Private G-code cleanup turns an already completed result into
        # stale history with this exact message. It is no longer retryable:
        # no native preset needs to remain registered merely for that record.
        archived_slice = (Q(status="completed") |
                          Q(status="stale", message="Private unsaved G-code removed; slice history retained."))
        if linked.exclude(archived_slice).exists():
            return _error(
                "This profile is still required by an unsliced, active or retryable "
                "slicing job. Delete or reassign those entries first.", 409)
        archived = linked.filter(archived_slice)
        archived.filter(printer_profile_id=profile.pk).update(printer_profile=None)
        archived.filter(filament_profile_id=profile.pk).update(filament_profile=None)
        archived.filter(process_profile_id=profile.pk).update(process_profile=None)
        try:
            profile.delete()
        except ProtectedError:
            return _error(
                "This profile is referenced by another protected record "
                "and cannot be removed.", 409)
    return JsonResponse({"removed": True, "profile_id": str(profile_id),
                         "source_file_preserved": True,
                         "completed_history_preserved": True})


@login_required
@require_http_methods(["GET"])
def profile_process_settings(request, profile_id):
    """Read editable native process settings from the user's resolved preset."""
    profile = SlicerProfile.objects.filter(
        pk=profile_id, owner=request.user, engine__in=["orcaslicer", "crealityprint", "bambustudio", "prusaslicer"], kind="process"
    ).select_related("file_asset").first()
    if not profile:
        return _error("Owned native slicing process profile not found.", 404)
    try:
        resolved = resolved_native_profile(profile)
        if profile.engine == "prusaslicer":
            from .slicer_prusa_process_settings import prusa_process_schema
            fields = prusa_process_schema(resolved)
        else:
            fields = process_schema(resolved)
    except (SlicerProfileError, ValueError, OSError):
        return _error("Native process settings could not be inspected.", 422)
    return JsonResponse({"profile_id": str(profile.pk), "engine": profile.engine,
                         "fields": fields, "scope": "global", "native_profile_unchanged": True})


@login_required
@require_http_methods(["GET"])
def profile_flush_defaults(request, profile_id):
    """Inspect engine-native process flushing defaults, without guessing slot mappings.

    A native matrix is indexed by slicer tools, not physical CFS slots.
    Creality's four-position project matrix may be assembled later from
    native process settings; do not imply that missing profile values are
    verified manufacturer purge amounts.
    """
    profile = SlicerProfile.objects.filter(
        pk=profile_id, owner=request.user,
        engine__in=["orcaslicer", "crealityprint", "bambustudio"], kind="process"
    ).select_related("file_asset").first()
    if not profile:
        return _error("Owned slicer process profile not found.", 404)
    try:
        raw = json.loads(resolved_native_profile(profile))
        multiplier = raw.get("flush_multiplier")
        if isinstance(multiplier, list):
            multiplier = multiplier[0] if len(multiplier) == 1 else None
        multiplier = float(multiplier) if multiplier is not None else None
        if multiplier is not None and (not math.isfinite(multiplier) or not 0.1 <= multiplier <= 3):
            multiplier = None
        prime = raw.get("enable_prime_tower")
        if isinstance(prime, list):
            prime = prime[0] if len(prime) == 1 else None
        enabled = None if prime is None else str(prime).lower() in {"1", "true"}
        matrix = raw.get("flush_volumes_matrix")
        if isinstance(matrix, list) and len(matrix) <= 256 and all(
            not isinstance(entry, bool) and str(entry).strip() for entry in matrix
        ):
            converted = [float(entry) for entry in matrix]
            if any(not math.isfinite(v) or not 0 <= v <= 20000 for v in converted):
                matrix = None
            else:
                count = math.isqrt(len(converted))
                matrix = converted if count >= 2 and count * count == len(converted) else None
        else:
            matrix = None
    except (SlicerProfileError, ValueError, TypeError, OSError, OverflowError):
        return _error("Native flushing values could not be inspected.", 422)
    return JsonResponse({
        "profile_id": str(profile.pk), "engine": profile.engine,
        "multiplier": multiplier,
        "prime_tower": enabled, "matrix": matrix,
        "tool_count": math.isqrt(len(matrix)) if matrix else None,
        "native_profile_unchanged": True,
        "physical_slots_mapped": False,
    })


@login_required
@require_http_methods(["GET"])
def profile_plate(request, profile_id):
    profile = SlicerProfile.objects.filter(
        pk=profile_id, owner=request.user, engine__in=["orcaslicer", "crealityprint", "bambustudio", "prusaslicer", "snapmakerorca"], kind="printer"
    ).select_related("file_asset").first()
    if not profile:
        return _error("Owned Orca or Creality machine profile not found.", 404)
    if profile.engine in ("orcaslicer", "crealityprint", "bambustudio"):
        try:
            geometry = (inspect_creality_plate(profile) if profile.engine == "crealityprint"
                        else inspect_bambu_plate(profile) if profile.engine == "bambustudio"
                        else inspect_orca_plate(profile))
        except SlicerProfileError:
            return _error("Native printer geometry could not be safely inspected.", 422)
    else:
        # Model/vendor metadata is not a validated printable-area polygon.
        # The frontend may display approved artwork against the configured
        # printer dimensions, but this never changes slice-fit validation.
        geometry = {"status": "unavailable", "reason": "Use printer build dimensions."}
    if profile.engine in ("orcaslicer", "crealityprint"):
        try:
            geometry["bed_types"] = inspect_engine_plates(profile)
        except (SlicerProfileError, ValueError, OSError, TypeError):
            geometry["bed_types"] = {"default": None, "supported": [],
                                     "default_source": "not declared"}
    if official_artwork_source(profile):
        geometry["artwork_url"] = reverse(
            "api-slicer-profile-artwork", kwargs={"profile_id": profile.pk}
        )
        geometry["artwork_source"] = "Imported official OrcaSlicer profile"
    if official_bed_model_source(profile):
        geometry["bed_model_url"] = reverse(
            "api-slicer-profile-bed-model", kwargs={"profile_id": profile.pk}
        )
    return JsonResponse({"profile_id": str(profile.pk), "plate": geometry})


@login_required
@require_http_methods(["GET"])
def profile_artwork(request, profile_id):
    """Serve only vetted same-origin artwork associated with an owned profile."""
    profile = SlicerProfile.objects.filter(
        pk=profile_id, owner=request.user, engine__in=["orcaslicer", "crealityprint", "bambustudio", "prusaslicer", "snapmakerorca"], kind="printer",
    ).select_related("file_asset").first()
    if not profile:
        return _error("Owned native printer profile not found.", 404)
    raw = cached_official_artwork(profile)
    if raw is None:
        return _error("Native artwork unavailable; use the MakerVault plate.", 404)
    response = HttpResponse(raw, content_type="image/svg+xml")
    response["X-Content-Type-Options"] = "nosniff"
    response["Content-Security-Policy"] = "default-src 'none'; style-src 'unsafe-inline'; sandbox"
    response["Cache-Control"] = "private, max-age=3600"
    return response


@login_required
@require_http_methods(["GET"])
def profile_bed_model(request, profile_id):
    """Serve a bounded, validated native STL underneath the interactive bed."""
    profile = SlicerProfile.objects.filter(
        pk=profile_id, owner=request.user,
        engine__in=["orcaslicer", "crealityprint", "bambustudio", "prusaslicer", "snapmakerorca"], kind="printer",
    ).select_related("file_asset").first()
    if not profile:
        return _error("Owned native printer profile not found.", 404)
    raw = cached_official_bed_model(profile)
    if raw is None:
        return _error("Native bed geometry unavailable; use the MakerVault plate.", 404)
    response = HttpResponse(raw, content_type="model/stl")
    response["X-Content-Type-Options"] = "nosniff"
    response["Cache-Control"] = "private, max-age=3600"
    return response


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
def save_job_gcode_to_library(request, job_id):
    """Explicit promotion of a completed private slicer output into G-code Files."""
    if not request.user.has_perm("core.add_fileasset"):
        return _error("You do not have permission to add G-code to the library.", 403)
    with transaction.atomic():
        job = SliceJob.objects.select_for_update().select_related("output_asset").filter(
            pk=job_id, owner=request.user, status="completed",
            output_asset__owner=request.user,
        ).first()
        if not job or not job.output_asset_id:
            return _error("Completed G-code output is not available.", 404)
        asset = job.output_asset
        if asset.category != "gcode":
            if asset.category != "other" or (asset.metadata or {}).get("generated_by") != "makervault-slicer":
                return _error("This output cannot be promoted to the G-code library.", 409)
            metadata = dict(asset.metadata or {})
            if metadata.get("slice_job_id") != str(job.pk) or metadata.get("extension") != ".gcode":
                return _error("The G-code output is not associated with this job.", 409)
            metadata["slicer_library_status"] = "saved"
            asset.category = "gcode"
            asset.metadata = metadata
            asset.full_clean()
            asset.save(update_fields=["category", "metadata", "updated_at"])
        job.message = "G-code saved to MakerVault library. Inspect before printing."
        job.save(update_fields=["message", "updated_at"])
    return JsonResponse({"job": serialise(job), "saved_to_library": True})


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
