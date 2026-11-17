"""Staging-only sequential 3MF combination probe for a saved Orca 2.5 draft.

No DB updates, G-code storage, printer upload, or printer start. All private
models and masks are loaded using the existing owner-scoped runtime helpers.
Only fixed, sanitized worker diagnostic categories are shown.
"""
import hashlib
import json
import uuid

from django.core.management.base import BaseCommand, CommandError

from core.models import FileAsset, SliceJob
from core.slicer_bed_dimensions import trusted_plate_dimensions
from core.slicer_execution import (
    MAX_INPUT, MAX_PROFILE, _read_owned_file, _execution_printer_profile,
)
from core.slicer_native_resolution import resolved_native_profile
from core.slicer_native_overrides import apply_orca_job_overrides
from core.slicer_paint_assets import expand_painted_settings
from core.slicer_plate_3mf import build_plate_3mf
from core.slicer_process_settings import apply_process_overrides
from core.slicer_variable_layers import audit_orca_variable_layers
from core.slicer_worker_client import SlicerWorkerError, run_remote_job


FEATURES = ("fuzzy_skin_paint", "seam_paint", "support_paint",
            "variable_layer_profile")
CASES = (
    ("plain-3mf", ()),
    ("variable-only", ("variable_layer_profile",)),
    ("fuzzy", ("fuzzy_skin_paint",)),
    ("fuzzy+variable", ("fuzzy_skin_paint", "variable_layer_profile")),
    ("fuzzy+seam", ("fuzzy_skin_paint", "seam_paint")),
    ("fuzzy+seam+variable", ("fuzzy_skin_paint", "seam_paint", "variable_layer_profile")),
    ("fuzzy+seam+support", ("fuzzy_skin_paint", "seam_paint", "support_paint")),
    ("all-four", FEATURES),
)


def selected_variant(original, fields):
    """Make a detached variant without modifying persisted paint references."""
    return {key: value for key, value in original.items()
            if key not in FEATURES or key in fields}


class Command(BaseCommand):
    help = ("Safely probe saved Orca 2.5 painting combinations using temporary "
            "worker jobs. No G-code or draft changes are saved.")

    def add_arguments(self, parser):
        parser.add_argument("job_id", type=uuid.UUID)
        parser.add_argument("--continue-on-failure", action="store_true",
                            help="Run later variants even after a failure.")
        parser.add_argument("--max-cases", type=int, default=len(CASES))
        parser.add_argument("--acknowledge-offline-test", action="store_true",
                            help="Explicitly allow isolated, non-printing worker probes.")

    def handle(self, *args, **options):
        # This operator-only command never stores a job result, sends G-code
        # to a printer or updates a draft. Require an explicit acknowledgment
        # even on development systems.
        if not options["acknowledge_offline_test"]:
            raise CommandError("Pass --acknowledge-offline-test to run isolated slices.")
        job = SliceJob.objects.select_related(
            "owner", "printer", "input_asset", "printer_profile",
            "filament_profile", "process_profile",
        ).filter(pk=options["job_id"]).first()
        if not job:
            raise CommandError("Saved slicing job not found.")
        if job.engine != "orcaslicer" or job.engine_version != "2.5.0":
            raise CommandError("This diagnostic requires OrcaSlicer 2.5.0.")
        if (job.settings or {}).get("multi_material_test") or (job.settings or {}).get("flush_settings"):
            raise CommandError("Multi-material and flushing jobs are not supported.")
        if not 1 <= options["max_cases"] <= len(CASES):
            raise CommandError("--max-cases must be between 1 and %s." % len(CASES))
        try:
            saved = expand_painted_settings(job.owner, job.settings or {})
            models = saved.get("plate_objects") or []
            if len(models) != 1:
                raise CommandError("Select a saved draft with exactly one plate model.")
            original = models[0]
            if isinstance(original.get("colour_paint"), dict) and (original["colour_paint"].get("regions") or original["colour_paint"].get("faces")):
                raise CommandError("Colour-painted drafts are not supported by this probe.")
            source = FileAsset.objects.filter(
                pk=original["asset_id"], owner_id=job.owner_id,
                category="mesh").first()
            if not source:
                raise CommandError("The private source STL is unavailable.")
            raw = _read_owned_file(source, job.owner_id, MAX_INPUT, "Plate STL")
            if source.sha256 and hashlib.sha256(raw).hexdigest() != source.sha256:
                raise CommandError("The original STL checksum does not match.")
            profiles = {}
            for kind in ("printer", "filament", "process"):
                profile = getattr(job, kind + "_profile")
                blob = _read_owned_file(
                    profile.file_asset, job.owner_id, MAX_PROFILE, "Native profile")
                if hashlib.sha256(blob).hexdigest() != profile.content_sha256:
                    raise CommandError("A native profile checksum does not match.")
                profiles[kind] = resolved_native_profile(profile)
            profiles["printer"] = _execution_printer_profile(
                job.printer_profile, profiles["printer"], profiles["process"])
            width, depth = trusted_plate_dimensions(job.printer_profile)
        except (ValueError, OSError, KeyError, TypeError) as exc:
            raise CommandError("Draft validation failed: " + str(exc)) from exc

        available = {key for key in FEATURES if
                     isinstance(original.get(key), dict) and
                     original[key].get("bands" if key == "variable_layer_profile"
                                       else "regions")}
        self.stdout.write("Read-only diagnostic. Stored draft, painting and G-code "
                          "library will not be modified.")
        self.stdout.write("Available: " + ", ".join(sorted(available)))
        if not available:
            raise CommandError("The selected draft contains no advanced painting or layer ranges.")
        failed = False
        for label, fields in CASES[:options["max_cases"]]:
            if not set(fields) <= available:
                self.stdout.write(label + ": SKIP (feature absent from draft)")
                continue
            item = selected_variant(original, fields)
            try:
                model = build_plate_3mf([(item, raw)], bed_width=width, bed_depth=depth)
                process, filament = apply_orca_job_overrides(
                    profiles["process"], profiles["filament"], job.plate,
                    [item], printer_profile=job.printer_profile)
                process = apply_process_overrides(
                    process, saved.get("process_overrides") or {})
                fuzzy_mode = str(json.loads(process).get("fuzzy_skin", "<missing>"))
                # Use new temporary request IDs. The worker never stores these
                # as persistent MakerVault jobs or returns G-code to a printer.
                result = run_remote_job(
                    uuid.uuid4(), job.engine, job.engine_version, model,
                    profiles["printer"], filament, process, model_format="3mf")
                if "variable_layer_profile" in fields:
                    audit_orca_variable_layers(
                        result.decode("utf-8"), item["variable_layer_profile"]["bands"])
                self.stdout.write(self.style.SUCCESS(
                    label + ": PASS (fuzzy=" + fuzzy_mode + ", G-code bytes=" +
                    str(len(result)) + ")"))
            except (ValueError, OSError, SlicerWorkerError) as exc:
                failed = True
                self.stdout.write(self.style.ERROR(
                    label + ": FAIL (" + type(exc).__name__ + ": " + str(exc)[:240] + ")"))
                if not options["continue_on_failure"]:
                    self.stdout.write("Stopped at first failure. Run with "
                                      "--continue-on-failure to collect the remaining cases.")
                    break
        if failed:
            raise CommandError("One or more offline variants failed. No data was changed.")
