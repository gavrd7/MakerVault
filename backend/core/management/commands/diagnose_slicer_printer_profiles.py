"""Read-only native cross-printer compatibility smoke test.

Uses explicitly selected, integrity-checked imported profiles and the pinned
isolated worker. This never creates a SliceJob, persists modified profiles,
runs printer API calls, or permits the resulting G-code to be printed.
"""
import hashlib
import io
import json
import math
import uuid
import zipfile
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
from core.slicer_native_material_palette import _single_positive_diameter
from core.slicer_native_resolution import resolved_native_profile
from core.slicer_plate_3mf import build_plate_3mf
from core.slicer_worker_client import run_remote_job
from core.slicer_tower_diagnostics import tower_deposition_metrics


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
            "tool0_selects": result["tool0_selects"],
            "tool1_selects": result["tool1_selects"],
            "note": "Native offline slicing; no physical printer validation."}


def _compatible_filament_diameter(filament_blobs, *, engine="orcaslicer"):
    """Validate each engine's native diameter representation, without guessing.

    Orca's one-element vector and Creality Print's scalar are different
    native schemas. Both require an exact positive bounded diameter, and
    mixed-diameter tool palettes remain forbidden for offline fixtures.
    """
    if engine not in {"orcaslicer", "crealityprint"}:
        raise ValueError("Unsupported native filament diameter encoding.")
    diameters = []
    for blob in filament_blobs:
        try:
            data = json.loads(blob)
        except (UnicodeDecodeError, TypeError, ValueError) as exc:
            raise ValueError("Invalid native filament preset.") from exc
        if not isinstance(data, dict):
            raise ValueError("Invalid native filament preset.")
        if engine == "orcaslicer":
            diameter = _single_positive_diameter(data)
        else:
            raw = data.get("filament_diameter")
            diameter = None
            if not isinstance(raw, (list, tuple, dict, bool)) and raw is not None:
                try:
                    parsed = float(raw)
                except (ValueError, TypeError, OverflowError):
                    pass
                else:
                    if math.isfinite(parsed) and 1 <= parsed <= 3.5:
                        diameter = parsed
        if diameter is None:
            raise ValueError("Native filament diameter is missing or invalid.")
        diameters.append(diameter)
    if not diameters or max(diameters) - min(diameters) > 0.001:
        raise ValueError("Mixed native filament diameters cannot be tested together.")
    return diameters[0]


def _read_creality_project_settings(project_blob):
    """Inspect only the generated effective native project configuration.

    The worker itself consumes the 3MF, not a standalone process JSON.
    Read exactly the setting file the native 3MF route receives.
    """
    try:
        with zipfile.ZipFile(io.BytesIO(project_blob)) as archive:
            names = archive.namelist()
            if len(names) != len(set(names)):
                raise ValueError("Duplicate Creality native archive entries.")
            data = archive.read("Metadata/project_settings.config")
    except (zipfile.BadZipFile, KeyError, OSError, ValueError) as exc:
        raise ValueError("Invalid self-contained Creality project settings.") from exc
    if len(data) > 4 * 1024 * 1024:
        raise ValueError("Creality native project settings exceed audit limit.")
    try:
        config = json.loads(data)
    except (UnicodeDecodeError, ValueError) as exc:
        raise ValueError("Invalid Creality native project settings JSON.") from exc
    if not isinstance(config, dict):
        raise ValueError("Creality native project settings must be an object.")
    return config


def _creality_flush_basis(project_config):
    """Fail closed on missing/invalid native matrix and multiplier evidence."""
    import math
    matrix = project_config.get("flush_volumes_matrix")
    if not isinstance(matrix, list) or len(matrix) != 16:
        raise ValueError("Creality native project requires its complete 4x4 matrix.")
    for value in matrix:
        try:
            number = float(value) if not isinstance(value, bool) else math.nan
        except (ValueError, TypeError, OverflowError):
            raise ValueError("Invalid native Creality matrix entry.") from None
        if not math.isfinite(number) or not 0 <= number <= 20000:
            raise ValueError("Invalid native Creality matrix entry.")
    multiplier = project_config.get("flush_multiplier")
    if multiplier is None:
        return float(matrix[1]), None
    if isinstance(multiplier, (bool, list, dict, tuple)):
        raise ValueError("Invalid Creality native scalar flush multiplier.")
    try:
        number = float(multiplier)
    except (ValueError, TypeError, OverflowError):
        raise ValueError("Invalid Creality native scalar flush multiplier.") from None
    if not math.isfinite(number) or not 0.1 <= number <= 3:
        raise ValueError("Invalid Creality native scalar flush multiplier.")
    return float(matrix[1]), number


def _creality_control_project(base, candidate):
    """Ensure no printer scripts or unrelated native fields were modified."""
    original = _read_creality_project_settings(base)
    test = _read_creality_project_settings(candidate)
    changed = {key for key in set(original) | set(test)
               if original.get(key) != test.get(key)}
    if not changed.issubset({
            "flush_multiplier", "flush_volumes_matrix", "flush_volumes_changed"}):
        raise ValueError("Unexpected native Creality project settings changed.")
    with (zipfile.ZipFile(io.BytesIO(base)) as before,
          zipfile.ZipFile(io.BytesIO(candidate)) as after):
        before_names = before.namelist()
        after_names = after.namelist()
        if set(before_names) != set(after_names):
            raise ValueError("Native Creality project entry set changed.")
        for name in before_names:
            if name == "Metadata/project_settings.config":
                continue
            if before.read(name) != after.read(name):
                raise ValueError("Native Creality project geometry or metadata changed.")
    return original, test, changed


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
        parser.add_argument("--name-contains", help="Filter local imported profile list by bounded name fragment")
        parser.add_argument("--printer-profile-id")
        parser.add_argument("--process-profile-id")
        parser.add_argument("--filament-profile-id", action="append", default=[])
        parser.add_argument("--topology", choices=SUPPORTED_TOPOLOGIES)
        parser.add_argument("--native", action="store_true",
                            help="Send ONLY disposable offline fixture to approved worker")
        parser.add_argument("--test-flush", action="store_true",
                            help="Run bounded native A/B flushing controls for Orca or Creality single-nozzle changers")

    def handle(self, *args, **opts):
        engine = opts["engine"]
        if opts["list_profiles"]:
            query = SlicerProfile.objects.filter(engine=engine)
            fragment = opts.get("name_contains")
            if fragment:
                if not 1 <= len(fragment) <= 100 or any(ord(ch) < 32 for ch in fragment):
                    raise CommandError("Invalid imported profile name filter.")
                query = query.filter(name__icontains=fragment)
            rows = list(query.order_by(
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
        try:
            filament_diameter = _compatible_filament_diameter(
                native["filaments"], engine=engine)
        except ValueError as exc:
            raise CommandError(str(exc)) from exc
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
            "filament_diameter_mm": filament_diameter,
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
                not cap.supported_for_encoding_only or count < 2):
            raise CommandError("Native flushing A/B test requires a supported single-nozzle changer.")
        # Reject missing/incompatible matrices *before* using worker time.
        first_flush_volume = None
        if opts["test_flush"] and engine == "orcaslicer":
            raw_matrix = json.loads(native["process"]).get("flush_volumes_matrix")
            if not isinstance(raw_matrix, list) or len(raw_matrix) != count * count:
                raise CommandError("No complete native flush matrix for directional A/B fixture.")
            try:
                first_flush_volume = float(raw_matrix[1])
            except (TypeError, ValueError, OverflowError):
                raise CommandError("Native T0-to-T1 flush volume is invalid.") from None
            if not 0 <= first_flush_volume <= 19950:
                raise CommandError("Native T0-to-T1 volume exceeds safe A/B fixture bounds.")
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
            def build_creality(flush=None):
                return build_creality_project_candidate(
                    geometry, printer=native["printer"], process=native["process"],
                    filaments=native["filaments"], bed_width=width, bed_depth=depth,
                    version=version, flush_settings=flush,
                    tool_bindings={"fixture-slot-0": 0, "fixture-slot-1": 1}
                    if flush is not None else None)
            model = build_creality()
            kwargs = {"model_format": "3mf",
                      "filament_profiles": native["filaments"],
                      "creality_native_project": True}
        def slice_native(process_blob, model_blob=None):
            return run_remote_job(
                uuid.uuid4(), engine, version, model if model_blob is None else model_blob,
                native["printer"], native["filaments"][0], process_blob,
                timeout_seconds=900, **kwargs)
        # Validate Creality controls and baseline provenance before any worker
        # execution; generated zero/140 fallback values are NOT user defaults.
        creality_controls = None
        if opts["test_flush"] and engine == "crealityprint":
            baseline_config = _read_creality_project_settings(model)
            first_flush_volume, native_multiplier = _creality_flush_basis(baseline_config)
            if not 0 <= first_flush_volume <= 19950:
                raise CommandError("Native Creality directional volume is outside safe A/B bounds.")
            # The imported K2 preset has no native multiplier: test 1.00
            # and 1.30 as EXPLICIT disposable controls, not inherited
            # defaults or changes to the user's saved profiles.
            multiplier_controls = (1.0, 1.3)
            def settings(multiplier=None, transition=None):
                return {
                    "multiplier": multiplier, "prime_tower": "native",
                    "transitions": [] if transition is None else [{
                        "from_slot_id": transition[0],
                        "to_slot_id": transition[1],
                        "volume_mm3": transition[2],
                    }],
                }
            creality_controls = [
                ("forward", build_creality(settings(
                    transition=("fixture-slot-0", "fixture-slot-1",
                                first_flush_volume + 25)))),
            ]
            for requested in multiplier_controls:
                creality_controls.append((
                    "multiplier_" + str(requested).replace(".", "_"),
                    build_creality(settings(multiplier=requested))))
            for name, candidate in creality_controls:
                original, changed, keys = _creality_control_project(model, candidate)
                if name == "forward":
                    if (float(changed["flush_volumes_matrix"][1]) !=
                            first_flush_volume + 25 or
                            changed["flush_volumes_matrix"][4] !=
                            original["flush_volumes_matrix"][4]):
                        raise CommandError("Creality forward directional fixture was not isolated.")
                    if changed.get("flush_multiplier") != original.get("flush_multiplier"):
                        raise CommandError("Creality native multiplier changed in directional fixture.")
                else:
                    requested = float(name.removeprefix("multiplier_").replace("_", "."))
                    if ("flush_volumes_matrix" in keys or
                            float(changed["flush_multiplier"]) != requested):
                        raise CommandError("Creality multiplier control changed directional volumes.")
        output = slice_native(native["process"])
        summary["native_run"] = "sliced"
        summary["baseline"] = _safe_native_result(output)
        if opts["test_flush"] and engine == "orcaslicer":
            first = first_flush_volume
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
        if creality_controls is not None:
            # Project packager overlays printer and process native settings.
            # If neither contains a matrix, its conservative 140mm3 values
            # are diagnostic placeholders, never vendor-calculated defaults.
            machine_source = json.loads(native["printer"])
            process_source = json.loads(native["process"])
            if "flush_volumes_matrix" in process_source:
                matrix_source = "resolved_native_process"
            elif "flush_volumes_matrix" in machine_source:
                matrix_source = "resolved_native_printer"
            else:
                matrix_source = "candidate_builder_140mm3_fallback_unverified"
            summary["creality_flush_basis"] = {
                "matrix_source": matrix_source,
                "baseline_t0_to_t1_mm3": first_flush_volume,
                "native_scalar_multiplier": native_multiplier,
                "multiplier_default_known": native_multiplier is not None,
            }
            baseline_metrics = _metrics(output)
            baseline_tower = tower_deposition_metrics(output)
            summary["native_tower_deposition_baseline"] = baseline_tower
            summary["creality_flush_controls"] = {}
            for name, candidate in creality_controls:
                result = slice_native(native["process"], candidate)
                measured = _metrics(result)
                tower = tower_deposition_metrics(result)
                summary["creality_flush_controls"][name] = {
                    **_safe_native_result(result),
                    "tower_deposition": tower,
                    "tower_comparison_available": (
                        baseline_tower["classification"] == "native_feature_marker"
                        and tower["classification"] == "native_feature_marker"),
                    "tower_xy_width_changed": (
                        tower["xy_width_mm"] != baseline_tower["xy_width_mm"]
                        if baseline_tower["classification"] == "native_feature_marker"
                        and tower["classification"] == "native_feature_marker" else None),
                    "tower_xy_depth_changed": (
                        tower["xy_depth_mm"] != baseline_tower["xy_depth_mm"]
                        if baseline_tower["classification"] == "native_feature_marker"
                        and tower["classification"] == "native_feature_marker" else None),
                    "tower_e_length_changed": (
                        tower["positive_e_length_mm"] != baseline_tower["positive_e_length_mm"]
                        if baseline_tower["classification"] == "native_feature_marker"
                        and tower["classification"] == "native_feature_marker" else None),
                    "gcode_changed": hashlib.sha256(result).digest() != hashlib.sha256(output).digest(),
                    "motion_changed": measured["motion_sha256"] != baseline_metrics["motion_sha256"],
                    "machine_commands_changed": measured["machine_command_sha256"] !=
                                                baseline_metrics["machine_command_sha256"],
                    "note": "Offline native comparison only; physical purge is unverified.",
                }
            summary["creality_flush_controls"]["forward"]["requested_t0_to_t1_mm3"] = first_flush_volume + 25
            summary["native_tool_selects_observed"] = {
                "t0": baseline_metrics["tool0_selects"],
                "t1": baseline_metrics["tool1_selects"],
                "both_tool_ids_seen": (
                    baseline_metrics["tool0_selects"] > 0
                    and baseline_metrics["tool1_selects"] > 0),
                "note": "Native tool ID observations, NOT physical CFS tool-change or purge proof.",
            }
            for requested in multiplier_controls:
                name = "multiplier_" + str(requested).replace(".", "_")
                summary["creality_flush_controls"][name]["requested_multiplier"] = requested
            summary["creality_flush_basis"]["multiplier_control_origin"] = (
                "explicit_disposable_1_00_vs_1_30_not_native_default")
        after = verified_installation().get(engine)
        if after != installed:
            raise CommandError("Pinned engine approval changed during offline diagnostics.")
        self.stdout.write(json.dumps(summary, indent=2))
