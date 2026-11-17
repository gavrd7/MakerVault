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

def range_probe_variants(original):
    """Pure copy-on-write comparison for saved native layer-height bands.

    Keep original thickness and duration. The relocated probes have deliberately
    simple, non-overlapping Z ranges and do not affect the saved draft.
    """
    profile = original.get("variable_layer_profile")
    bands = (profile or {}).get("bands") if isinstance(profile, dict) else None
    if not isinstance(bands, list) or len(bands) != 1:
        return ()
    band = bands[0]
    try:
        original_from = float(band["from_mm"])
        original_to = float(band["to_mm"])
        thickness = float(band["layer_mm"])
    except (KeyError, TypeError, ValueError):
        return ()
    span = original_to - original_from
    if not 0 < span <= 50:
        return ()
    # Compare the same height and duration with shifted intervals. A position
    # effect (such as narrow tip geometry) can then be distinguished from a
    # fundamentally unsupported profile or malformed 3MF.
    test_bands = []
    for lower in (5.0, 12.0, 22.0, 32.0):
        if abs(lower - original_from) < 0.0005 or lower + span > 47:
            continue
        test_bands.append((
            "range-at-" + str(int(lower)) + "mm",
            [{"from_mm": lower, "to_mm": lower + span, "layer_mm": thickness}],
        ))
    return tuple(test_bands)


def layer_thickness_probe_variants(original):
    """Read-only probes at the same Z range using alternate layer heights."""
    profile = original.get("variable_layer_profile")
    bands = (profile or {}).get("bands") if isinstance(profile, dict) else None
    if not isinstance(bands, list) or len(bands) != 1:
        return ()
    band = bands[0]
    try:
        lower, upper, original_height = (float(band[key]) for key in
                                         ("from_mm", "to_mm", "layer_mm"))
    except (ValueError, TypeError, KeyError):
        return ()
    if not 0 <= lower < upper <= 1000:
        return ()
    return tuple((
        "layer-height-" + format(height, ".2f") + "mm",
        [{"from_mm": lower, "to_mm": upper, "layer_mm": height}],
    ) for height in (0.16, 0.20, 0.24)
      if abs(height - original_height) > 0.0001)


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
        parser.add_argument("--probe-layer-heights", action="store_true",
                            help="Compare 0.16, 0.20 and 0.24mm native ranges.")
        parser.add_argument("--probe-layer-ranges", action="store_true",
                            help="Compare copies of the saved Z band at several heights.")
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
            effective_process = json.loads(profiles["process"])
            effective_printer = json.loads(profiles["printer"])
            if not isinstance(effective_process, dict) or not isinstance(effective_printer, dict):
                raise CommandError("Resolved native preset is not an object.")
        except (ValueError, OSError, KeyError, TypeError) as exc:
            raise CommandError("Draft validation failed: " + str(exc)) from exc

        available = {key for key in FEATURES if
                     isinstance(original.get(key), dict) and
                     original[key].get("bands" if key == "variable_layer_profile"
                                       else "regions")}
        self.stdout.write("Read-only diagnostic. Stored draft, painting and G-code "
                          "library will not be modified.")
        self.stdout.write("Available: " + ", ".join(sorted(available)))
        # A small allowlist of numeric native settings is safe to display.
        # Never print arbitrary user profile fields or scripts.
        for source, preset, keys in (
            ("process", effective_process, ("layer_height", "initial_layer_print_height",
                "line_width", "outer_wall_line_width", "inner_wall_line_width",
                "top_surface_line_width")),
            ("printer", effective_printer, ("min_layer_height", "max_layer_height",
                "nozzle_diameter")),
        ):
            summary = {key: preset[key] for key in keys
                       if key in preset and isinstance(preset[key], (int, float, list, str))
                       and len(str(preset[key])) < 100}
            self.stdout.write("Effective " + source + " numeric settings: " +
                              json.dumps(summary, sort_keys=True))

        if not available:
            raise CommandError("The selected draft contains no advanced painting or layer ranges.")
        failed = False
        variants = []
        for label, fields in CASES[:options["max_cases"]]:
            if not set(fields) <= available:
                self.stdout.write(label + ": SKIP (feature absent from draft)")
                continue
            variants.append((label, selected_variant(original, fields), fields))
        if options["probe_layer_ranges"] and "variable_layer_profile" in available:
            for label, bands in range_probe_variants(original):
                updated = selected_variant(original, ("variable_layer_profile",))
                updated["variable_layer_profile"] = {"version": 1, "bands": bands}
                variants.append((label, updated, ("variable_layer_profile",)))
            self.stdout.write("Saved layer ranges: " +
                json.dumps(original["variable_layer_profile"]["bands"], sort_keys=True))
        if options["probe_layer_heights"] and "variable_layer_profile" in available:
            for label, bands in layer_thickness_probe_variants(original):
                updated = selected_variant(original, ("variable_layer_profile",))
                updated["variable_layer_profile"] = {"version": 1, "bands": bands}
                variants.append((label, updated, ("variable_layer_profile",)))
        for label, item, fields in variants:
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
                profile_height = effective_process.get("layer_height")
                target_bands = (item.get("variable_layer_profile") or {}).get("bands", [])
                if target_bands and len(target_bands) == 1 and (
                    isinstance(profile_height, (int, float))
                    and abs(float(profile_height) - float(target_bands[0]["layer_mm"])) < .0001
                ):
                    self.stdout.write(self.style.WARNING(
                        label + ": INCONCLUSIVE — target layer height equals native "
                        "process baseline; success does not prove the override was applied."))
                else:
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
