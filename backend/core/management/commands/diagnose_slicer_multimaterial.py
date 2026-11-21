"""Read-only replay of one owned saved multi-material Orca slicing job.

Inspect native 3MF tool annotations and palette before an optional isolated
worker test. Never change SliceJob, G-code library or printer state.
"""
import hashlib
import io
import json
import uuid
import zipfile
from collections import Counter
from types import SimpleNamespace
from defusedxml import ElementTree as ET

from django.core.management.base import BaseCommand, CommandError

from core.models import FileAsset, SliceJob
from core.slicer_bed_dimensions import trusted_plate_dimensions
from core.slicer_execution import (
    MAX_INPUT, MAX_PROFILE, _execution_printer_profile, _read_owned_file,
)
from core.slicer_flush_settings import apply_orca_flush_settings
from core.slicer_multimaterial_execution import prepare_job_multimaterial
from core.slicer_native_overrides import apply_orca_job_overrides
from core.slicer_native_resolution import resolved_native_profile
from core.slicer_paint_assets import expand_painted_settings
from core.slicer_process_settings import apply_process_overrides
from core.slicer_worker_client import SlicerWorkerError, run_remote_job

CORE_NS = "http://schemas.microsoft.com/3dmanufacturing/core/2015/02"


class Command(BaseCommand):
    help = "Inspect an existing native multicolour job without modifying any data."

    def add_arguments(self, parser):
        parser.add_argument("job_id", type=uuid.UUID)
        parser.add_argument("--probe-worker", action="store_true")
        parser.add_argument("--acknowledge-offline-test", action="store_true")

    def handle(self, *args, **opts):
        if opts["probe_worker"] and not opts["acknowledge_offline_test"]:
            raise CommandError("Worker probing requires --acknowledge-offline-test.")
        job = SliceJob.objects.select_related(
            "owner", "printer", "input_asset", "printer_profile",
            "filament_profile", "process_profile",
        ).filter(pk=opts["job_id"]).first()
        if not job:
            raise CommandError("Saved slicing job not found.")
        if job.engine != "orcaslicer" or job.engine_version != "2.5.0":
            raise CommandError("This diagnostic requires OrcaSlicer 2.5.0.")
        saved = expand_painted_settings(job.owner, job.settings or {})
        if saved.get("multi_material_test") is not True:
            raise CommandError("This is not an offline native multi-material job.")
        objects = saved.get("plate_objects") or []
        if not 1 <= len(objects) <= 12:
            raise CommandError("A valid saved plate is required.")
        # A detached in-memory job view: do not save expanded paint.
        job.settings = saved
        source_models = []
        for item in objects:
            source = FileAsset.objects.filter(
                pk=item["asset_id"], owner_id=job.owner_id, category="mesh"
            ).first()
            if not source:
                raise CommandError("A referenced private mesh is missing.")
            raw = _read_owned_file(source, job.owner_id, MAX_INPUT, "Plate STL")
            if source.sha256 and hashlib.sha256(raw).hexdigest() != source.sha256:
                raise CommandError("Source mesh checksum mismatch.")
            source_models.append((item, raw))
        width, depth = trusted_plate_dimensions(job.printer_profile)
        try:
            result = prepare_job_multimaterial(
                job, source_models, bed_width=width, bed_depth=depth)
        except (ValueError, KeyError, TypeError) as exc:
            raise CommandError("Native material preparation failed: " + str(exc)) from exc
        self.stdout.write("Read-only native multicolour diagnostic: " + str(job.pk))
        self.stdout.write("Model instances: " + str(len(objects)))
        self.stdout.write("Native tools: " + str(len(result["filament_profiles"])))
        self.stdout.write("Logical tool assignment: " + repr(result["native_tool_indices"]))
        self.stdout.write("Expected G-code tools: " + repr(sorted(result["expected_tools"])))
        with zipfile.ZipFile(io.BytesIO(result["model_3mf"])) as archive:
            root = ET.fromstring(archive.read("3D/3dmodel.model"))
            counts = Counter()
            for triangle in root.findall(
                ".//{%s}triangle" % CORE_NS
            ):
                if triangle.get("paint_color") is not None:
                    counts[triangle.get("paint_color")] += 1
            manifest = ET.fromstring(archive.read("Metadata/model_settings.config"))
            object_tools = [
                entry.get("value") for node in manifest if node.tag == "object"
                for entry in node if entry.get("key") == "extruder"
            ]
            self.stdout.write("Native object extruders: " + repr(object_tools))
            self.stdout.write("Painted native triangle states: " +
                              repr(dict(sorted(counts.items()))))
            self.stdout.write("3MF archive bytes: " + str(len(result["model_3mf"])))
        if not opts["probe_worker"]:
            self.stdout.write(
                "Inspection only. Add --probe-worker --acknowledge-offline-test "
                "for an isolated non-printing native slice.")
            return
        profiles = {}
        for kind in ("printer", "filament", "process"):
            profile = getattr(job, kind + "_profile")
            blob = _read_owned_file(profile.file_asset, job.owner_id, MAX_PROFILE, "Native profile")
            if hashlib.sha256(blob).hexdigest() != profile.content_sha256:
                raise CommandError("Native preset checksum mismatch.")
            profiles[kind] = resolved_native_profile(profile)
        profiles["printer"] = _execution_printer_profile(
            job.printer_profile, profiles["printer"], profiles["process"])
        process, filament = apply_orca_job_overrides(
            profiles["process"], profiles["filament"], job.plate,
            objects, printer_profile=job.printer_profile)
        process = apply_process_overrides(
            process, saved.get("process_overrides") or {})
        if saved.get("flush_settings") is not None:
            routes = [
                SimpleNamespace(slot_id=slot_id, tool_index=tool)
                for slot_id, tool in result["tool_bindings"].items()
            ]
            process = apply_orca_flush_settings(
                process, saved["flush_settings"], routes=routes,
                tool_count=len(result["filament_profiles"]),
                topology=result["topology"])
        palette = list(result["filament_profiles"])
        palette[0] = filament
        try:
            output = run_remote_job(
                uuid.uuid4(), job.engine, job.engine_version,
                result["model_3mf"], profiles["printer"], filament, process,
                model_format="3mf", filament_profiles=tuple(palette))
        except SlicerWorkerError as exc:
            raise CommandError("Isolated worker refused offline test: " + str(exc)) from exc
        self.stdout.write("Worker accepted input; G-code bytes: " + str(len(output)))
        self.stdout.write("No files saved; no printer submission performed.")
