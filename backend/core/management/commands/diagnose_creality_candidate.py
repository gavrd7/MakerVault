"""Generate a temporary, owner-scoped candidate from an existing Creality draft.

Host-admin diagnostic only. Does not queue a slice or send printer commands.
The candidate contains private geometry and profiles; the staging orchestration
script deletes its temporary copies after the isolated CLI test.
"""
import hashlib
import json
from pathlib import Path
import uuid
import tempfile

from django.core.management.base import BaseCommand, CommandError

from core.models import FileAsset, SliceJob
from core.slicer_execution import _read_owned_file, MAX_INPUT, MAX_PROFILE
from core.slicer_multimaterial_execution import prepare_creality_positioned_project
from core.slicer_creality_project import build_creality_project_candidate
from core.slicer_native_resolution import resolved_native_profile
from core.slicer_process_settings import apply_process_overrides
from core.slicer_bed_dimensions import trusted_plate_dimensions


def candidate_for_job(job):
    if (job.engine != "crealityprint" or not job.engine_version.startswith("7.3.")
            or (job.settings or {}).get("multi_material_test") is not True):
        raise ValueError("Select an existing two-material Creality 7.3 project.")
    objects = (job.settings or {}).get("plate_objects") or []
    if len(objects) != 2 or not all(isinstance(obj, dict) for obj in objects):
        raise ValueError("Only the existing two-model test is supported.")
    source = []
    for obj in objects:
        asset = FileAsset.objects.filter(
            pk=obj.get("asset_id"), owner_id=job.owner_id, category="mesh").first()
        if asset is None:
            raise ValueError("The original owned source model is missing.")
        raw = _read_owned_file(asset, job.owner_id, MAX_INPUT, "Plate STL")
        if asset.sha256 and hashlib.sha256(raw).hexdigest() != asset.sha256:
            raise ValueError("An original STL has changed.")
        source.append((obj, raw))
    width, depth = trusted_plate_dimensions(job.printer_profile)
    plate = prepare_creality_positioned_project(
        job, source, bed_width=width, bed_depth=depth)
    native = []
    for kind in ("printer", "filament", "process"):
        profile = getattr(job, kind + "_profile")
        if profile is None or profile.owner_id != job.owner_id:
            raise ValueError("An owned native profile is missing.")
        original = _read_owned_file(profile.file_asset, job.owner_id,
                                    MAX_PROFILE, "Native profile")
        if hashlib.sha256(original).hexdigest() != profile.content_sha256:
            raise ValueError("An imported preset has changed.")
        native.append(resolved_native_profile(profile))
    native[2] = apply_process_overrides(
        native[2], (job.settings or {}).get("process_overrides") or {})
    return build_creality_project_candidate(
        plate["project_geometry"], printer=native[0], process=native[2],
        filaments=plate["filament_profiles"], version=job.engine_version,
        prime_tower=(job.settings or {}).get("prime_tower"),
        bed_width=width, bed_depth=depth)


class Command(BaseCommand):
    help = "Export the latest failed Creality two-material job to a private temporary native 3MF."

    def add_arguments(self, parser):
        parser.add_argument("--job-id", help="Optional specific owned Creality job UUID")
        parser.add_argument("--output", required=True)

    def handle(self, *args, **options):
        path = Path(options["output"])
        if (path.parent != Path(tempfile.gettempdir()) or path.suffix != ".3mf"
                or path.exists() or path.is_symlink()):
            raise CommandError("Choose a fresh private /tmp/*.3mf path.")
        if options["job_id"]:
            try:
                job_id = uuid.UUID(options["job_id"])
            except ValueError:
                raise CommandError("Invalid job UUID.") from None
            job = SliceJob.objects.filter(pk=job_id).select_related(
                "printer_profile", "filament_profile", "process_profile").first()
        else:
            job = SliceJob.objects.filter(
                engine="crealityprint", status="failed",
                settings__multi_material_test=True,
            ).select_related(
                "printer_profile", "filament_profile", "process_profile").first()
        if job is None:
            raise CommandError("No failed Creality two-material draft was found.")
        try:
            candidate = candidate_for_job(job)
            with path.open("xb") as dest:
                dest.write(candidate)
            path.chmod(0o600)
        except Exception as exc:
            path.unlink(missing_ok=True)
            raise CommandError("Native project candidate export failed: " +
                               type(exc).__name__) from None
        self.stdout.write("Temporary native Creality candidate exported.")
