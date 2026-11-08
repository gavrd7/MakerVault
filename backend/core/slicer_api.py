"""Owner-scoped slicer drafts and engine discovery; no execution endpoints yet."""
import json
import os
import math
import re
import uuid
import hashlib
from pathlib import Path
from decimal import Decimal, InvalidOperation

from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.db import IntegrityError, transaction
from django.db.models.deletion import ProtectedError
from django.views.decorators.http import require_http_methods

from .models import FileAsset, Printer, SliceJob, Spool, SlicerProfile
from .slicer_engines import engine_catalogue, get_engine
from .slicer_profiles import SlicerProfileError, inspect_native_profile
from .slicer_profile_edit import SETTINGS as EDITABLE_PROFILE_SETTINGS, customise_native_json
from .slicer_profile_lineage import inspect_orca_lineage
from .slicer_mesh import inspect_stl, MeshInspectionError, MAX_INSPECTION_BYTES
from .slicer_bed import inspect_orca_plate, inspect_creality_plate
from .slicer_official_chain import official_profile_chain
from .slicer_creality_official_profiles import (
    search_creality_profiles, fetch_creality_profile, available_creality_vendors,
    official_catalogue_models as creality_catalogue_models,
    ENGINE_VERSION as OFFICIAL_CRE_VERSION, SOURCE as OFFICIAL_CRE_SOURCE,
    REF as OFFICIAL_CRE_REF,
)
from .slicer_official_profiles import (
    OfficialProfileError, search_official_profiles, fetch_official_profile, available_official_vendors,
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


def serialise(job, installed=None):
    # Private STL inputs are exposed only through this owner-scoped job, so a
    # saved plate can be edited again without appearing in the Files library.
    source_ids = {str(job.input_asset_id)}
    source_ids.update(str(item.get("asset_id")) for item in
                      (job.settings or {}).get("plate_objects", []) if isinstance(item, dict))
    temporary_inputs = [{
        "id": str(asset.pk), "name": asset.name,
        "filename": str((asset.metadata or {}).get("original_name") or asset.name),
        "category": "mesh", "url": asset.file.url if asset.file else "",
    } for asset in FileAsset.objects.filter(owner=job.owner, pk__in=source_ids,
                                              metadata__slicer_temporary=True)]
    can_slice = False
    if installed:
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
        "input_asset": {"id": str(job.input_asset_id), "name": job.input_asset.name},
        "printer": {"id": str(job.printer_id), "name": job.printer.name},
        "spool": {"id": str(job.spool_id), "name": job.spool.spool_id} if job.spool_id else None,
        "output_asset_id": str(job.output_asset_id) if job.output_asset_id else None,
        "output_asset": {
            "id": str(job.output_asset.pk),
            "name": job.output_asset.name,
            "filename": (job.output_asset.metadata or {}).get("original_name") or job.output_asset.name,
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


def _draft_plate_settings(user, input_asset, settings):
    """Persist preview-only plate geometry; never compile it into slicer flags."""
    if settings in ({}, None):
        return {}
    if not isinstance(settings, dict) or set(settings) - {"plate_objects", "save_gcode_to_library"}:
        raise ValueError("Unsupported slicer plate settings.")
    save_to_library = settings.get("save_gcode_to_library", False)
    if not isinstance(save_to_library, bool):
        raise ValueError("G-code library preference must be true or false.")
    if "plate_objects" not in settings:
        return {"save_gcode_to_library": save_to_library}
    objects = settings["plate_objects"]
    if not isinstance(objects, list) or not 1 <= len(objects) <= 12:
        raise ValueError("The visual build plate supports one to twelve model instances.")
    seen = set()
    saved = []
    for item in objects:
        required = {"instance_id", "asset_id", "x_mm", "y_mm", "rotation_deg",
                    "scale_percent", "color"}
        if (not isinstance(item, dict) or not required.issubset(item)
                or set(item) - required - {"scale_xyz_percent"}):
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
        for key, bound in (("x_mm", 10000), ("y_mm", 10000), ("rotation_deg", 360), ("scale_percent", 400)):
            raw = item[key]
            if isinstance(raw, bool) or not isinstance(raw, (int, float)) or not math.isfinite(raw):
                raise ValueError("Plate coordinates must be finite numbers.")
            if key == "scale_percent" and not 5 <= raw <= bound:
                raise ValueError("Plate scale must be between 5% and 400%.")
            if key != "scale_percent" and abs(raw) > bound:
                raise ValueError("Plate transform exceeds its allowed range.")
            values[key] = round(float(raw), 3)
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
        saved.append({"instance_id": instance_id, "asset_id": str(asset_id),
                      **values, "color": color.lower()})
    if saved[0]["asset_id"] != str(input_asset.pk):
        raise ValueError("The first plate model must match the selected primary STL.")
    return {"plate_objects": saved, "save_gcode_to_library": save_to_library}


def _draft(user, data):
    if not isinstance(data, dict) or len(json.dumps(data)) > 8192:
        raise ValueError("Slice configuration must be a small JSON object.")
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
    settings_data = _draft_plate_settings(user, input_asset, settings_data)
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

    return SliceJob.objects.create(
        owner=user, input_asset=input_asset, printer=printer, spool=spool,
        **native_profiles,
        engine=engine.key, engine_version=version,
        **native_labels,
        nozzle_mm=nozzle, plate=_preset(data, "plate", 80) if "plate" in data else "default",
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
    if not filename.lower().endswith(".stl") or not 0 < size <= MAX_INSPECTION_BYTES:
        return _error("Choose a nonempty STL no larger than 32 MiB.")
    try:
        ensure_storage_capacity(request.user, size)
        data = uploaded.read(MAX_INSPECTION_BYTES + 1)
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
    """Remove only private slicing inputs no longer referenced by any job."""
    ids = {str(job.input_asset_id)}
    ids.update(str(item.get("asset_id")) for item in
               (job.settings or {}).get("plate_objects", []) if isinstance(item, dict))
    for asset in FileAsset.objects.filter(pk__in=ids, owner=job.owner,
                                           metadata__slicer_temporary=True):
        if SliceJob.objects.filter(owner=job.owner, input_asset=asset).exists():
            continue
        if any(str(item.get("asset_id")) == str(asset.pk)
               for settings in SliceJob.objects.filter(owner=job.owner).values_list("settings", flat=True)
               for item in (settings or {}).get("plate_objects", [])
               if isinstance(item, dict)):
            continue
        stored = asset.file
        asset.delete()
        if stored:
            stored.delete(save=False)


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
            raw = stream.read(MAX_INSPECTION_BYTES + 1)
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
        if row["key"] in installed:
            row.update({"available": True, "enabled": True, "status": "validated",
                        "installed_version": installed[row["key"]]["version"]})
    return JsonResponse({
        "engines": rows,
        "worker_configured": bool(installed),
        "can_verify_profiles": request.user.is_superuser,
        # Deployment intent is distinct from a healthy, approved engine.
        # Never infer an installed container merely because code is present.
        "deployment_enabled": os.environ.get("MAKERVAULT_SLICER_EXECUTION_ENABLED") == "1",
        "preview_enabled": os.environ.get("MAKERVAULT_SLICER_PREVIEW_ENABLED") == "1" and request.user.is_superuser,
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


@login_required
@require_http_methods(["GET", "POST"])
def jobs(request):
    if request.method == "GET":
        installed = verified_installation()
        return JsonResponse({
            "jobs": [serialise(job, installed) for job in _rows(request.user)[:100]],
            "worker_configured": bool(installed),
            "can_cancel": request.user.has_perm("core.change_slicejob"),
            "can_delete": request.user.has_perm("core.delete_slicejob"),
        })
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
    if request.method == "DELETE":
        if not request.user.has_perm("core.delete_slicejob"):
            return _error("You do not have permission to delete slicing jobs.", 403)
        # The status check must happen under the row lock. A worker must not
        # claim a queued job while its source is being deleted.
        with transaction.atomic():
            job = _rows(request.user).select_for_update(of=("self",)).filter(pk=job_id).first()
            if not job:
                return _error("Slice job not found.", 404)
            if job.status not in {"draft", "failed", "cancelled", "stale"}:
                return _error("Only drafts and inactive failed/cancelled jobs can be deleted.", 409)
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
    }


@login_required
@require_http_methods(["GET", "POST"])
def official_profiles(request):
    """Search/import native candidates from pinned official engine catalogues."""
    if request.method == "GET":
        selected = request.GET.get("engine", "orcaslicer")
        if request.GET.get("catalogues") == "1":
            try:
                native = get_engine(selected)
            except ValueError as exc:
                return _error(str(exc))
            sources = {
                "orcaslicer": (available_official_vendors, OFFICIAL_ORCA_REF),
                "crealityprint": (available_creality_vendors, OFFICIAL_CRE_REF),
            }
            provider = sources.get(selected)
            return JsonResponse({
                "engine": selected,
                "vendors": provider[0]() if provider else [],
                "ref": provider[1] if provider else None,
                "native_profile_format": native.profile_format,
                "manual_import_available": True,
                "official_search_available": bool(provider),
                "verified_for_execution": False,
            })
        if request.GET.get("models") == "1":
            model_catalogues = {"orcaslicer": orca_catalogue_models,
                                "crealityprint": creality_catalogue_models}
            provider = model_catalogues.get(selected)
            if not provider:
                return _error("This slicer has no official printer catalogue.")
            try:
                models = provider(request.GET.get("vendor", "Creality"))
            except OfficialProfileError as exc:
                return _error(str(exc), 400)
            return JsonResponse({"engine": selected, "models": models})
        searcher = {
            "orcaslicer": search_official_profiles,
            "crealityprint": search_creality_profiles,
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
                                    "crealityprint": creality_catalogue_models}
                if chosen_model not in model_catalogues[selected](request.GET.get("vendor", "Creality")):
                    return _error("Choose a printer model listed in the official catalogue.")
                printer_model = chosen_model
            args = (
                request.GET.get("q", ""),
                request.GET.get("kind", "printer"),
                request.GET.get("vendor", "Creality"),
            )
            results = searcher(*args, printer_model=printer_model) if printer_model else searcher(*args)
            results["printer_model_filter"] = printer_model
        except OfficialProfileError as exc:
            return _error(str(exc), 503 if "source" in str(exc).lower() or "contact" in str(exc).lower() else 400)
        return JsonResponse(results)
    if not request.user.has_perm("core.add_fileasset"):
        return _error("You do not have permission to import official native profiles.", 403)
    if len(request.body) > 4096:
        return _error("Official profile selection is too large.", 413)
    try:
        selection = json.loads(request.body.decode("utf-8"))
        if not isinstance(selection, dict) or set(selection) - {"engine", "vendor", "kind", "name", "sub_path"}:
            raise ValueError("Invalid official profile selection.")
        engine = selection.get("engine", "orcaslicer")
        providers = {
            "orcaslicer": (OFFICIAL_ORCA_VERSION, OFFICIAL_ORCA_SOURCE, OFFICIAL_ORCA_REF, fetch_official_profile),
            "crealityprint": (OFFICIAL_CRE_VERSION, OFFICIAL_CRE_SOURCE, OFFICIAL_CRE_REF, fetch_creality_profile),
        }
        if engine not in providers:
            return _error("Official import is not available for this engine.")
        version, source, ref, fetcher = providers[engine]
        kind = selection.get("kind")
        vendor = selection.get("vendor", "Creality")
        name = selection.get("name")
        subpath = selection.get("sub_path")
        if not isinstance(name, str) or len(name) > 200:
            raise ValueError("Invalid native profile name.")
        if SlicerProfile.objects.filter(
            owner=request.user, engine=engine,
            engine_version=version, kind=kind, name=name,
        ).exists():
            return _error("This exact official preset has already been imported.", 409)
        # Fetch and validate the complete bounded parent chain *before*
        # mutating the database. Never install a partial official preset.
        chain = official_profile_chain(engine, kind, name, subpath, vendor)
        prepared = []
        for native_name, native_subpath, raw in chain:
            existing = SlicerProfile.objects.filter(
                owner=request.user, engine=engine,
                engine_version=version, kind=kind, name=native_name,
            ).first()
            if existing:
                # Different manufacturer catalogues can reuse a native parent
                # name with different contents. Never splice one vendor's
                # settings into another vendor's inheritance chain.
                import hashlib
                if existing.content_sha256 != hashlib.sha256(raw).hexdigest():
                    raise ValueError(
                        "Native preset name conflicts with a different imported profile: "
                        + native_name[:120] + ". Preserve both upstream profiles; "
                        "this engine/version needs separately scoped parent identities."
                    )
                continue
            asset = FileAsset(
                owner=request.user, name=native_name + ".json", category="source",
                metadata={"original_name": native_name + ".json", "extension": ".json"},
            )
            asset.file = ContentFile(raw, name="official-" + engine + "-profile.json")
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
                    provenance=provenance, content_sha256=digest, status="candidate",
                )
                created_names.append(native_name)
            profile = SlicerProfile.objects.get(
                owner=request.user, engine=engine,
                engine_version=version, kind=kind, name=name,
            )
    except (OfficialProfileError, ValueError, TypeError, UnicodeDecodeError, SlicerProfileError) as exc:
        return _error(str(exc))
    except IntegrityError:
        return _error("The selected official profile is already registered.", 409)
    return JsonResponse({
        "profile": _profile_summary(profile), "engine_version": version,
        "imported_profiles": created_names, "parent_chain_length": len(chain),
        "execution_available": False,
        "warning": "Official profile and available parent chain imported as unverified candidates. A real engine fixture is still required.",
    }, status=201)


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


@login_required
@require_http_methods(["GET", "POST"])
def customise_profile(request, profile_id):
    """Clone a native JSON preset, applying only bounded GUI-supported changes."""
    profile = SlicerProfile.objects.filter(
        pk=profile_id, owner=request.user, engine__in=["orcaslicer", "crealityprint"]
    ).select_related("file_asset").first()
    if not profile:
        return _error("An owned Orca or Creality native profile is required.", 404)
    if profile.kind not in EDITABLE_PROFILE_SETTINGS:
        return _error("Unsupported native profile type.")
    if request.method == "GET":
        current = {}
        available = {}
        try:
            with profile.file_asset.file.open("rb") as source:
                raw = source.read(1024 * 1024 + 1)
            properties = json.loads(raw.decode("utf-8-sig"))
            if not isinstance(properties, dict):
                raise ValueError("Unsupported native profile.")
            for key, limits in EDITABLE_PROFILE_SETTINGS[profile.kind].items():
                if key not in properties:
                    continue
                available[key] = limits
                value = properties.get(key)
                if isinstance(value, list):
                    value = value[0] if value else None
                try:
                    numeric = float(value.removesuffix("%") if isinstance(value, str) else value)
                except (ValueError, TypeError):
                    continue
                if math.isfinite(numeric) and limits[0] <= numeric <= limits[1]:
                    current[key] = numeric
        except (OSError, ValueError, UnicodeDecodeError):
            return _error("Cannot inspect original native profile.", 422)
        return JsonResponse({
            "profile": _profile_summary(profile),
            "settings": {name: {"min": limits[0], "max": limits[1],
                               "current": current.get(name)}
                         for name, limits in available.items()},
            "warning": "Custom presets are unverified; original native preset is preserved.",
        })
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
        with profile.file_asset.file.open("rb") as source:
            original = source.read(1024 * 1024 + 1)
        edited = customise_native_json(original, profile.kind, name, data["settings"])
        asset = FileAsset(
            owner=request.user, name=name + ".json", category="source",
            metadata={"original_name": name + ".json", "extension": ".json",
                      "slicer_custom_source_profile_id": str(profile.id)},
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


@login_required
@require_http_methods(["DELETE"])
def delete_profile(request, profile_id):
    """Delete only this user's profile registration; preserve its source FileAsset.

    Slices retain immutable native-profile references. Protected records cannot
    be removed until their dependent jobs have been resolved separately.
    """
    if not request.user.has_perm("core.delete_slicerprofile"):
        return _error("You do not have permission to remove slicer profiles.", 403)
    profile = SlicerProfile.objects.filter(pk=profile_id, owner=request.user).first()
    if profile is None:
        return _error("Slicer profile not found.", 404)
    try:
        profile.delete()
    except ProtectedError:
        return _error("This profile is referenced by saved slicing jobs and cannot be removed.", 409)
    return JsonResponse({"removed": True, "profile_id": str(profile_id),
                         "source_file_preserved": True})


@login_required
@require_http_methods(["GET"])
def profile_plate(request, profile_id):
    profile = SlicerProfile.objects.filter(
        pk=profile_id, owner=request.user, engine__in=["orcaslicer", "crealityprint"], kind="printer"
    ).select_related("file_asset").first()
    if not profile:
        return _error("Owned Orca or Creality machine profile not found.", 404)
    try:
        geometry = (inspect_creality_plate(profile) if profile.engine == "crealityprint"
                    else inspect_orca_plate(profile))
    except SlicerProfileError:
        return _error("Native printer geometry could not be safely inspected.", 422)
    return JsonResponse({"profile_id": str(profile.pk), "plate": geometry})


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
