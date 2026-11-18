"""Export a private native 3MF reference for offline Creality diagnostics.

Select an inventory/library FileAsset belonging to the owner of a selected
failed Creality slicing job. Never inspect another user's private storage.
No database changes, printer actions, or permanent exports.
"""
import uuid
import zipfile
import io
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.db.models import Q

from core.models import FileAsset, SliceJob
from core.slicer_execution import _read_owned_file

MAX_REFERENCE = 32 * 1024 * 1024


class Command(BaseCommand):
    help = "Export an owner-scoped inventory 3MF for safe structural comparison."

    def add_arguments(self, parser):
        parser.add_argument("--job-id")
        group = parser.add_mutually_exclusive_group(required=True)
        group.add_argument("--asset-id")
        group.add_argument("--name")
        parser.add_argument("--output", required=True)

    def handle(self, *args, **options):
        output = Path(options["output"])
        if (output.parent != Path("/tmp") or output.suffix.lower() != ".3mf"
                or output.exists() or output.is_symlink()):
            raise CommandError("Choose a fresh private /tmp/*.3mf output path.")
        jobs = SliceJob.objects.filter(
            engine="crealityprint", status="failed",
            settings__multi_material_test=True,
        )
        if options["job_id"]:
            try:
                selected_job_id = uuid.UUID(options["job_id"])
            except ValueError:
                raise CommandError("Invalid slicing job UUID.") from None
            jobs = jobs.filter(pk=selected_job_id)
        job = jobs.order_by("-created_at").first()
        if job is None:
            raise CommandError("No matching failed Creality job is available.")
        owned = FileAsset.objects.filter(owner_id=job.owner_id).filter(
            category__in=["slicer", "mesh", "cad", "archive", "other"]
        )
        if options["asset_id"]:
            try:
                selected_id = uuid.UUID(options["asset_id"])
            except ValueError:
                raise CommandError("Invalid reference asset UUID.") from None
            asset = owned.filter(pk=selected_id).first()
        else:
            name = options["name"]
            if (not isinstance(name, str) or len(name) > 255 or
                    "/" in name or "\\" in name or
                    not name.lower().endswith(".3mf")):
                raise CommandError("Reference name must be one 3MF filename.")
            # Compare both logical record names and the encrypted storage's
            # basename. No arbitrary glob or filesystem access.
            stem = name[:-4]
            candidates = [
                entry for entry in owned.filter(
                    Q(name__iexact=name) | Q(name__iexact=stem)
                    | Q(file__iendswith="/" + name)
                ).order_by("-created_at")[:21]
                if entry.file and (
                    entry.name.casefold() == name.casefold()
                    or (entry.name.casefold() == stem.casefold()
                        and (entry.metadata or {}).get("extension", "").lower() == ".3mf")
                    or Path(entry.file.name).name.casefold() == name.casefold())
            ]
            if len(candidates) != 1:
                raise CommandError(
                    "Reference inventory filename matched %d assets. "
                    "Select a specific FileAsset UUID with --asset-id." %
                    len(candidates))
            asset = candidates[0]
        if asset is None or not asset.file:
            raise CommandError("No owned reference asset with that identifier.")
        try:
            data = _read_owned_file(asset, job.owner_id, MAX_REFERENCE,
                                    "Creality reference")
            with zipfile.ZipFile(io.BytesIO(data)) as source:
                members = set(source.namelist())
                if ("Metadata/project_settings.config" not in members or
                        "3D/3dmodel.model" not in members):
                    raise ValueError("Not a native 3MF project.")
            with output.open("xb") as stream:
                stream.write(data)
            output.chmod(0o600)
        except (OSError, ValueError, zipfile.BadZipFile) as exc:
            output.unlink(missing_ok=True)
            raise CommandError("Reference inventory asset is not a readable native 3MF.") from None
        self.stdout.write("Private owner-scoped Creality 3MF reference exported.")
