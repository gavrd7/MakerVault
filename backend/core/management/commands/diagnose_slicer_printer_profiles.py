"""Read-only native cross-printer compatibility smoke test.

Uses explicitly selected, integrity-checked imported profiles and the pinned
isolated worker. This never creates a SliceJob, persists modified profiles,
runs printer API calls, or permits the resulting G-code to be printed.
"""
import hashlib
import json
import uuid
from types import SimpleNamespace

from django.core.management.base import BaseCommand, CommandError

from core.models import SlicerProfile
from core.slicer_approval import fixture_stl, _approved_gcode
from core.slicer_bed_dimensions import trusted_plate_dimensions
from core.management.commands.diagnose_creality_paint_features import _metrics
from core.slicer_creality_project import (
    build_creality_positioned_plate, build_creality_project_candidate,
)
from core.slicer_execution import verified_installation
from core.slicer_flush_adapters import (
    apply_orca_native_flush, resolve_flush_capability,
)
from core.slicer_native_compatibility import check_native_compatibility
from core.slicer_native_resolution import resolved_native_profile
from core.slicer_plate_3mf import build_plate_3mf
from core.slicer_worker_client import run_remote_job


SUPPORTED_TOPOLOGIES = ("single_nozzle_changer", "independent_toolheads",
                        "toolchanger", "idex", "manual_filament_change",
                        "single_material", "unknown")


def _fixture_items(count, width, depth):
    """Distinct 10mm tetrahedra on an origin-aligned rectangular bed."""
    if type(count) is not int or not 1 <= count <= 4:
        raise ValueError("Native compatibility fixture supports one to four materials.")
    if min(width, depth) < 90 or width > 1000 or depth > 1000:
        raise ValueError("Native fixture requires a verified 90–1000mm rectangular bed.")
    gap = 18.0
    centre = (count - 1) / 2
    return [
        ({
            "instance_id": "fixture-%d" % tool, "x_mm": (tool - centre) * gap,
            "y_mm": 0, "rotation_deg": 0, "scale_percent": 100,
        }, fixture_stl())
        for tool in range(count)
    ]


def _safe_native_result(data):
    """Report evidence without returning G-code, machine macros or paths."""
    result = _metrics(data)
    return {"gcode_sha256": _approved_gcode(data),
            "gcode_bytes": len(data),
            "motion_sha256": result["motion_sha256"],
            "machine_command_sha256": result["machine_command_sha256"],
            "g1_with_extrusion": result["g1_with_extrusion"],
            "note": "Native offline slicing; no physical printer validation."}


def _native_nozzle_count(printer_blob):
    """Count nozzles from the *resolved native machine profile*, never names."""
    try:
        printer = json.loads(printer_blob)
    except (TypeError, ValueError, UnicodeDecodeError) as exc:
        raise ValueError("Native machine nozzle information is invalid.") from exc
    if not isinstance(printer, dict):
        raise ValueError("Native machine must be a JSON object.")
    values = printer.get("nozzle_diameter")
    if not isinstance(values, list) or not 1 <= len(values) <= 16:
        raise ValueError("Native machine must declare one to sixteen nozzle diameters.")
    import math
    for item in values:
        try:
            diameter = float(item) if not isinstance(item, bool) else math.nan
        except (ValueError, TypeError):
            raise ValueError("Invalid native machine nozzle diameter.") from None
        if not math.isfinite(diameter) or not 0.1 <= diameter <= 3:
            raise ValueError("Invalid native machine nozzle diameter.")
    return len(values)


def _same_native_pair(profile, owner, engine, version, kind):
    return (profile and profile.owner_id == owner
            and profile.engine == engine and profile.engine_version == version
            and profile.kind == kind and profile.status in {"candidate", "verified"})


class Command(BaseCommand):
    help = "Audit or offline-slice exact selected printer profiles without printer communication."

    def add_arguments(self, parser):
        parser.add_argument("--engine", choices=("orcaslicer", "crealityprint"), required=True)
        parser.add_argument("--list-profiles", action="store_true",
                            help="List up to 100 available imported native profile identities")
        parser.add_argument("--printer-profile-id")
        parser.add_argument("--process-profile-id")
        parser.add_argument("--filament-profile-id", action="append", default=[])
        parser.add_argument("--topology", choices=SUPPORTED_TOPOLOGIES)
        parser.add_argument("--native", action="store_true",
                            help="Send ONLY disposable offline fixture to approved worker")
        parser.add_argument("--test-flush", action="store_true",
                            help="For native Orca single-nozzle tests, compare one directional matrix override")

    def handle(self, *args, **opts):
        engine = opts["engine"]
        if opts["list_profiles"]:
            rows = list(SlicerProfile.objects.filter(engine=engine).order_by(
                "engine_version", "kind", "pk").values(
                "pk", "name", "source_scope", "kind", "engine_version", "status")[:100])
            self.stdout.write(json.dumps({"schema": 1, "engine": engine,
                "profiles": [{"id": str(row["pk"]), "name": str(row["name"])[:120],
                              "source_scope": str(row["source_scope"])[:100],
                              "kind": row["kind"], "version": row["engine_version"],
                              "status": row["status"]} for row in rows],
                "truncated_at": 100, "note": "Listing only, not native validation."}, indent=2))
            return
        if opts["test_flush"] and not opts["native"]:
            raise CommandError("--test-flush requires --native.")
        if not opts["topology"]:
            raise CommandError("Explicit --topology required; printer names cannot imply topology.")
        source_ids = [opts["printer_profile_id"], opts["process_profile_id"],
                      *opts["filament_profile_id"]]
        if (not 3 <= len(source_ids) <= 6 or any(x is None for x in source_ids)):
            raise CommandError("Select printer, process and one to four native filament profile IDs.")
        try:
            profile_ids = [uuid.UUID(v) for v in source_ids]
        except (TypeError, ValueError):
            raise CommandError("Invalid selected profile UUID.") from None
        records = {
            str(p.pk): p for p in SlicerProfile.objects.select_related(
                "file_asset").filter(pk__in=profile_ids)
        }
        if len(records) != len(set(profile_ids)):
            raise CommandError("Some selected imported native profiles were not found.")
        printer, process, *filaments = [records[str(key)] for key in profile_ids]
        owner = printer.owner_id
        version = printer.engine_version
        if (not _same_native_pair(printer, owner, engine, version, "printer")
                or not _same_native_pair(process, owner, engine, version, "process")
                or any(not _same_native_pair(p, owner, engine, version, "filament")
                       for p in filaments)):
            raise CommandError("Native profiles must match one owner, engine and exact version.")
        # A repeated native filament preset for two logical tools is permitted:
        # they are distinct physical spool assignments but share material type.
        native = {
            "printer": resolved_native_profile(printer),
            "process": resolved_native_profile(process),
            "filaments": [resolved_native_profile(p) for p in filaments],
        }
        for kind, raw in (("printer", native["printer"]),
                          ("process", native["process"]),
                          *[("filament", blob) for blob in native["filaments"]]):
            check_native_compatibility(engine, version, kind, raw)
        count = len(filaments)
        width, depth = trusted_plate_dimensions(printer)
        try:
            nozzles = _native_nozzle_count(native["printer"])
        except ValueError as exc:
            raise CommandError(str(exc)) from exc
        if opts["topology"] == "single_nozzle_changer" and nozzles != 1:
            raise CommandError("A single-nozzle changer requires exactly one native nozzle.")
        if opts["topology"] in ("independent_toolheads", "toolchanger", "idex"):
            if nozzles != count or count < 2:
                raise CommandError("Independent toolhead fixture needs one verified native nozzle per logical tool.")
            if opts["topology"] == "idex" and nozzles != 2:
                raise CommandError("IDEX fixture requires two verified nozzles.")
        cap = resolve_flush_capability(
            engine, opts["topology"], nozzle_count=nozzles,
            material_count=count)
        summary = {
            "schema": 1, "engine": engine, "version": version,
            "topology": opts["topology"], "logical_material_count": count,
            "native_nozzle_count": nozzles,
            "bed_mm": [width, depth],
            "native_flush_encoding_supported": cap.supported_for_encoding_only,
            "unsupported_reason": cap.reason,
            "physical_purge": "unverified",
            "offline_only": True, "native_run": "not_requested",
        }
        if not opts["native"]:
            self.stdout.write(json.dumps(summary, indent=2))
            return
        installed = verified_installation().get(engine)
        if not installed or installed.get("version") != version:
            raise CommandError("Matching authenticated pinned engine is not available.")
        if count > 1 and engine == "crealityprint" and (
                count != 2 or opts["topology"] != "single_nozzle_changer"):
            raise CommandError("Creality multi-material fixture only supports its verified two-tool single-nozzle project.")
        if opts["test_flush"] and (
                engine != "orcaslicer" or not cap.supported_for_encoding_only or count < 2):
            raise CommandError("Directional native flush test requires verified Orca single-nozzle changer.")
        if count == 1:
            model = fixture_stl()
            kwargs = {}
        elif engine == "orcaslicer":
            items = _fixture_items(count, width, depth)
            model = build_plate_3mf(items, bed_width=width, bed_depth=depth,
                                    native_tool_indices=list(range(count)))
            kwargs = {"model_format": "3mf", "filament_profiles": native["filaments"]}
        else:
            items = _fixture_items(count, width, depth)
            geometry = build_creality_positioned_plate(
                items, bed_width=width, bed_depth=depth,
                tool_ids=list(range(count)))
            model = build_creality_project_candidate(
                geometry, printer=native["printer"], process=native["process"],
                filaments=native["filaments"], bed_width=width, bed_depth=depth,
                version=version)
            kwargs = {"model_format": "3mf",
                      "filament_profiles": native["filaments"],
                      "creality_native_project": True}
        def slice_native(process_blob):
            return run_remote_job(
                uuid.uuid4(), engine, version, model, native["printer"],
                native["filaments"][0], process_blob,
                timeout_seconds=900, **kwargs)
        output = slice_native(native["process"])
        summary["native_run"] = "sliced"
        summary["baseline"] = _safe_native_result(output)
        if opts["test_flush"]:
            values = json.loads(native["process"])
            matrix = values.get("flush_volumes_matrix")
            if not isinstance(matrix, list) or len(matrix) != count * count:
                raise CommandError("Baseline native slice passed, but no complete verified native flush matrix for A/B test.")
            first = float(matrix[1])
            if not 0 <= first <= 19950:
                raise CommandError("Native directional volume cannot be changed safely.")
            modified = apply_orca_native_flush(
                native["process"], {
                    "prime_tower": "native", "multiplier": None,
                    "transitions": [{
                        "from_slot_id": "fixture-slot-0",
                        "to_slot_id": "fixture-slot-1",
                        "volume_mm3": first + 25,
                    }],
                },
                routes=[SimpleNamespace(slot_id="fixture-slot-%d" % n,
                                        tool_index=n) for n in range(count)],
                tool_count=count, topology="single_nozzle_changer")
            control = slice_native(modified)
            summary["directional_matrix_control"] = {
                "baseline_raw_mm3": first,
                "requested_raw_mm3": first + 25,
                **_safe_native_result(control),
                "gcode_changed": hashlib.sha256(output).digest() != hashlib.sha256(control).digest(),
                "motion_changed": _metrics(output)["motion_sha256"] != _metrics(control)["motion_sha256"],
                "machine_commands_changed": (
                    _metrics(output)["machine_command_sha256"] !=
                    _metrics(control)["machine_command_sha256"]),
                "note": "Motion or command change is stronger than metadata difference, but is NOT physical purge validation.",
            }
        after = verified_installation().get(engine)
        if after != installed:
            raise CommandError("Pinned engine approval changed during offline diagnostics.")
        self.stdout.write(json.dumps(summary, indent=2))
