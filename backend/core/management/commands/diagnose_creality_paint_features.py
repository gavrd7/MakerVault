"""Offline Creality 7.3 painted-feature smoke matrix using an existing successful K2 slice.

Runs the same pinned, authenticated worker as ordinary MakerVault slicing. It
never saves a SliceJob, uploads G-code, writes printer settings or starts a print.
An accepted 3MF is NOT proof that Creality honoured the annotation: compare
reported G-code metrics with the unmodified baseline and review inconclusive cases.
"""
import copy
import hashlib
import json
import math
import re
import uuid

from django.core.management.base import BaseCommand, CommandError

from core.models import SliceJob, FileAsset
from core.slicer_bed_dimensions import trusted_plate_dimensions
from core.slicer_creality_project import build_creality_project_candidate
from core.slicer_execution import MAX_INPUT, _read_owned_file, verified_installation
from core.slicer_multimaterial_execution import prepare_creality_positioned_project
from core.slicer_native_resolution import resolved_native_profile
from core.slicer_native_support_paint import _fingerprint
from core.slicer_paint_assets import expand_painted_settings
from core.slicer_plate_3mf import _triangles
from core.slicer_plate_types import apply_creality_plate
from core.slicer_process_settings import apply_process_overrides
from core.slicer_worker_client import run_remote_job

CASES = ("baseline", "support", "seam", "fuzzy", "variable", "flushing")


def _patch_for_model(stl):
    """Produce a valid model-local brush patch from actual STL triangles."""
    triangles = list(_triangles(stl))
    if not triangles:
        raise ValueError("No STL triangles")
    minima = [min(p[i] for tri in triangles for p in tri) for i in range(3)]
    maxima = [max(p[i] for tri in triangles for p in tri) for i in range(3)]
    origin = ((minima[0] + maxima[0]) / 2,
              (minima[1] + maxima[1]) / 2, minima[2])
    local = [
        [tuple(float(point[i]) - origin[i] for i in range(3)) for point in tri]
        for tri in triangles
    ]
    # A single small central region keeps this diagnostic fast and bounded.
    face_index = next((i for i, face in enumerate(local)
                       if math.dist(face[0], face[1]) > 1 and
                       math.dist(face[0], face[2]) > 1), 0)
    face = local[face_index]
    centre = [sum(point[i] for point in face) / 3 for i in range(3)]
    patch = [[(point[i] + centre[i]) / 2 for i in range(3)] for point in face]
    return _fingerprint(local), face_index, patch, maxima[2] - minima[2]


def _metrics(gcode):
    if not isinstance(gcode, bytes) or len(gcode) > 64 * 1024 * 1024:
        raise ValueError("Invalid diagnostic G-code")
    text = gcode.decode("utf-8", errors="replace")
    zs = [float(x) for x in re.findall(r"(?im)^;Z:\s*([0-9]+(?:\.[0-9]+)?)\s*$", text)]
    layers = sorted(set(round(x, 4) for x in zs))
    steps = sorted(set(round(b-a, 3) for a,b in zip(layers,layers[1:])
                       if .049 <= b-a <= .501))
    return {
        "sha256": hashlib.sha256(gcode).hexdigest(),
        "bytes": len(gcode),
        "g1_with_extrusion": len(re.findall(
            r"(?im)^\s*G0?1\s+[^\r\n]*\bE[-+]?\d", text)),
        "tool0_selects": len(re.findall(r"(?im)^\s*T0(?:\s|$)", text)),
        "tool1_selects": len(re.findall(r"(?im)^\s*T1(?:\s|$)", text)),
        "support_type_markers": len(re.findall(
            r"(?im)^;\s*(?:TYPE|FEATURE):\s*.*support", text)),
        "layer_count_from_z_comments": len(layers),
        "observed_layer_steps_mm": steps[:24],
    }


class Command(BaseCommand):
    help = "Slice read-only painted variants with the pinned Creality worker and compare G-code."

    def add_arguments(self, parser):
        parser.add_argument("--job-id", help="Existing successful one-model Creality CFS painted slice UUID")
        parser.add_argument("--only", choices=CASES[1:], help="Only one feature plus baseline")

    def handle(self, *args, **options):
        jobs = SliceJob.objects.select_related(
            "owner", "printer", "printer_profile", "filament_profile",
            "process_profile").filter(
            engine="crealityprint", status="completed",
            settings__multi_material_test=True)
        if options["job_id"]:
            try:
                identifier = uuid.UUID(options["job_id"])
            except ValueError:
                raise CommandError("Invalid job UUID") from None
            jobs = jobs.filter(pk=identifier)
        selected = None
        for candidate in jobs.order_by("-created_at")[:30]:
            try:
                expanded = expand_painted_settings(candidate.owner, candidate.settings or {})
            except (OSError, ValueError):
                continue
            objects = expanded.get("plate_objects") or []
            if (len(objects) == 1 and isinstance(objects[0], dict)
                    and (objects[0].get("colour_paint") or {}).get("regions")):
                selected = (candidate, expanded)
                break
        if not selected:
            raise CommandError("No completed one-object colour-painted Creality CFS job found. Supply --job-id.")
        job, settings = selected
        installed = verified_installation().get("crealityprint")
        if not installed or installed["version"] != job.engine_version:
            raise CommandError("Saved job's exact Creality binary is not approved in the current worker.")
        source = settings["plate_objects"][0]
        asset = FileAsset.objects.filter(
            owner=job.owner, pk=source["asset_id"], category="mesh").first()
        if asset is None:
            raise CommandError("Original owned mesh unavailable.")
        raw_stl = _read_owned_file(asset, job.owner_id, MAX_INPUT, "Diagnostic mesh")
        if asset.sha256 and hashlib.sha256(raw_stl).hexdigest() != asset.sha256:
            raise CommandError("Original STL checksum changed.")
        fingerprint, face, polygon, height = _patch_for_model(raw_stl)
        width, depth = trusted_plate_dimensions(job.printer_profile)
        printer_native = resolved_native_profile(job.printer_profile)
        process_native = resolved_native_profile(job.process_profile)
        process_native = apply_process_overrides(
            process_native, settings.get("process_overrides") or {})
        if height < 3:
            raise CommandError("Source model is too short for a variable-layer test.")
        lo, hi = round(max(.5, height*.25), 3), round(min(height-.5, height*.75), 3)
        if lo >= hi:
            raise CommandError("Source model has no safe variable-layer interval.")
        marker = {"version": 2, "signature": fingerprint,
                  "regions": [{"slot": 0, "patches": [
                      {"face": face, "polygon": polygon}]}]}
        variants = ["baseline", options["only"]] if options["only"] else list(CASES)
        results = {}
        baseline = None
        for feature in variants:
            copy_settings = copy.deepcopy(settings)
            obj = copy_settings["plate_objects"][0]
            for name in ("support_paint", "seam_paint", "fuzzy_skin_paint",
                         "variable_layer_profile"):
                obj.pop(name, None)
            if feature == "support":
                obj["support_paint"] = copy.deepcopy(marker)
            elif feature == "seam":
                value = copy.deepcopy(marker)
                value["regions"][0]["slot"] = 0
                obj["seam_paint"] = value
            elif feature == "fuzzy":
                obj["fuzzy_skin_paint"] = copy.deepcopy(marker)
            elif feature == "variable":
                obj["variable_layer_profile"] = {
                    "version": 1, "bands": [
                        {"from_mm": lo, "to_mm": hi, "layer_mm": .12}]}
            # Deliberately change only native flush values in this test case.
            copy_settings["flush_settings"] = None
            job.settings = copy_settings  # In-memory only: NEVER call .save().
            try:
                prepared = prepare_creality_positioned_project(
                    job, [(obj, raw_stl)], bed_width=width, bed_depth=depth)
                first = prepared["filament_profiles"][0]
                process, first = apply_creality_plate(
                    process_native, first, job.plate,
                    printer_profile=job.printer_profile)
                flush = None
                if feature == "flushing":
                    mapped = {tool: slot for slot, tool in prepared["tool_bindings"].items()}
                    flush = {
                        "prime_tower": "native", "multiplier": 1.25,
                        "transitions": [
                            {"from_slot_id": mapped[0], "to_slot_id": mapped[1],
                             "volume_mm3": 370},
                            {"from_slot_id": mapped[1], "to_slot_id": mapped[0],
                             "volume_mm3": 175},
                        ],
                    }
                package = build_creality_project_candidate(
                    prepared["project_geometry"], printer=printer_native,
                    process=process, filaments=prepared["filament_profiles"],
                    version=job.engine_version, tool_colours=prepared["tool_colours"],
                    prime_tower=copy_settings.get("prime_tower"),
                    flush_settings=flush, tool_bindings=prepared["tool_bindings"],
                    layer_ranges=prepared.get("layer_ranges"),
                    bed_width=width, bed_depth=depth)
                data = run_remote_job(
                    uuid.uuid4(), "crealityprint", job.engine_version,
                    package, printer_native, prepared["filament_profiles"][0], process,
                    model_format="3mf", filament_profiles=prepared["filament_profiles"],
                    creality_native_project=True, timeout_seconds=900)
                metrics = _metrics(data)
                if feature == "baseline":
                    baseline = metrics
                else:
                    metrics["toolpath_changed_from_baseline"] = (
                        metrics["sha256"] != baseline["sha256"])
                    metrics["observation"] = (
                        "Changed G-code; specific painting effect still needs toolpath audit."
                        if metrics["toolpath_changed_from_baseline"]
                        else "No whole-file difference; native effect not demonstrated.")
                results[feature] = {"status": "sliced", **metrics}
            except Exception as exc:
                # Do not disclose private native profile contents, G-code, or
                # server paths. Worker errors have bounded diagnostic labels.
                results[feature] = {
                    "status": "failed", "error_class": type(exc).__name__,
                    "error": str(exc)[:180] if type(exc).__name__ in (
                        "SlicerWorkerError", "SlicerProfileError", "MaterialRoutingError")
                        else "Check MakerVault application logs for this diagnostic.",
                }
                if feature == "baseline":
                    break
            self.stdout.write(feature + ": " + results[feature]["status"])
        self.stdout.write(json.dumps({
            "schema": 1, "job_id": str(job.pk), "engine": job.engine_version,
            "note": "Offline diagnostics only. Different G-code is not proof of correct paint effect.",
            "cases": results,
        }, indent=2))
