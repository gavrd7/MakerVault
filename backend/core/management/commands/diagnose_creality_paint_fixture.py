"""Read-only synthetic Creality painting smoke matrix without a saved SliceJob.

Uses selected *existing* imported native profiles. Constructs only disposable
in-memory model/project 3MF and sends it to the approved isolated worker;
never creates files, database jobs, printer commands, or profile overrides.
A successful native slice is NOT printer approval or semantic correctness.
"""
import io
import json
import uuid
import zipfile
from xml.etree import ElementTree as ET

from django.core.management.base import BaseCommand, CommandError

from core.models import SlicerProfile
from core.slicer_approval import _approved_gcode
from core.slicer_bed_dimensions import trusted_plate_dimensions
from core.slicer_creality_project import (
    build_creality_positioned_plate, build_creality_project_candidate,
)
from core.slicer_native_compatibility import check_native_compatibility
from core.slicer_native_resolution import resolved_native_profile
from core.slicer_variable_layers import orca_layer_config_ranges
from core.slicer_worker_client import run_remote_job
from core.slicer_creality_spatial_audit import (
    painted_triangle_bounds, spatial_comparison, spatial_deposition_cells,
)
from core.slicer_execution import verified_installation
from core.management.commands.diagnose_slicer_printer_profiles import (
    _same_native_pair, _native_nozzle_count, _creality_toolchange_macro_audit,
)
from core.management.commands.diagnose_creality_paint_features import (
    _cantilever_fixture_stl, _cantilever_support_marker,
    _cantilever_wall_marker, _patch_for_model, _geometry_control_project,
    _feature_role_audit, _metrics,
)

CASES = ("baseline", "support", "seam", "fuzzy", "variable", "flushing")
_NAMESPACE = "{http://schemas.microsoft.com/3dmanufacturing/core/2015/02}"


def _synthetic_fixture_item(raw, feature):
    """Return a deterministic in-memory two-colour object with one paint channel."""
    signature, face, polygon, height = _patch_for_model(raw)
    if not 3 < height <= 260:
        raise ValueError("Unsupported synthetic fixture height.")
    colour_paint = {
        "version": 2, "signature": signature,
        "palette": [
            {"color": "#111111", "label": "Synthetic dark"},
            {"color": "#FADD4D", "label": "Synthetic light"},
        ],
        "regions": [{"slot": 1, "patches": [
            {"face": face, "polygon": polygon},
        ]}],
    }
    obj = {
        "instance_id": "synthetic-offline-fixture",
        "x_mm": 0, "y_mm": 0, "rotation_deg": 0,
        "rotation_xyz_deg": [0, 0], "scale_percent": 100,
        "scale_xyz_percent": [100, 100, 100],
        "color": "#111111", "colour_paint": colour_paint,
    }
    if feature == "support":
        obj["support_paint"] = _cantilever_support_marker(raw)
    elif feature == "seam":
        obj["seam_paint"] = _cantilever_wall_marker(raw)
    elif feature == "fuzzy":
        obj["fuzzy_skin_paint"] = _cantilever_wall_marker(raw)
    elif feature == "variable":
        obj["variable_layer_profile"] = {
            "version": 1, "bands": [
                {"from_mm": 3.0, "to_mm": min(height - 1.0, 15.0),
                 "layer_mm": .12},
            ],
        }
    return obj


def _fixture_project(raw, feature, *, machine, process, filaments, width, depth):
    obj = _synthetic_fixture_item(raw, feature)
    geometry = build_creality_positioned_plate(
        [(obj, raw)], bed_width=width, bed_depth=depth,
        tool_ids=[0], colour_tool_maps=({1: 1},),
    )
    layers = (orca_layer_config_ranges([(obj, raw)])
              if feature == "variable" else None)
    selected_process = process
    if feature == "support":
        # The process-only change is disposable; never save it as a preset.
        settings = json.loads(process)
        settings["enable_support"] = "1"
        settings["support_type"] = "normal(manual)"
        selected_process = json.dumps(
            settings, separators=(",", ":")).encode("utf-8")
    flush = None
    if feature == "flushing":
        flush = {
            "prime_tower": "native", "multiplier": 1.25,
            "transitions": [
                {"from_slot_id": "fixture-dark", "to_slot_id": "fixture-light",
                 "volume_mm3": 370},
                {"from_slot_id": "fixture-light", "to_slot_id": "fixture-dark",
                 "volume_mm3": 175},
            ],
        }
    project = build_creality_project_candidate(
        geometry, printer=machine, process=selected_process,
        filaments=filaments, version="7.3.1",
        tool_colours=("#111111", "#FADD4D"),
        flush_settings=flush,
        tool_bindings=({"fixture-dark": 0, "fixture-light": 1}
                       if flush is not None else None),
        layer_ranges=layers,
        bed_width=width, bed_depth=depth,
    )
    # Assert the native paint metadata has survived the actual final project.
    with zipfile.ZipFile(io.BytesIO(project)) as archive:
        root = ET.fromstring(archive.read("3D/3dmodel.model"))
        triangles = list(root.iter(_NAMESPACE + "triangle"))
        if not triangles or not any("paint_color" in tri.attrib for tri in triangles):
            raise ValueError("Synthetic native colour annotation was lost.")
        key = {"support": "paint_supports", "seam": "paint_seam",
               "fuzzy": "paint_fuzzy_skin"}.get(feature)
        if key and not any(key in tri.attrib for tri in triangles):
            raise ValueError("Synthetic native feature annotation was lost.")
    return project, selected_process


class Command(BaseCommand):
    help = ("Synthetic offline Creality 7.3.1 painted smoke tests using existing "
            "native K2 profiles, without a saved job or physical printer.")

    def add_arguments(self, parser):
        parser.add_argument("--printer-profile-id", required=True)
        parser.add_argument("--process-profile-id", required=True)
        parser.add_argument("--filament-profile-id", action="append", required=True)
        parser.add_argument("--only", choices=CASES[1:])
        parser.add_argument("--deep", action="store_true",
                            help="Compare each semantic feature against exact same-geometry control")

    def handle(self, *args, **options):
        values = [options["printer_profile_id"], options["process_profile_id"],
                  *options["filament_profile_id"]]
        if len(values) != 4:
            raise CommandError("Exactly one printer, one process and two filaments required.")
        try:
            ids = [uuid.UUID(x) for x in values]
        except (TypeError, ValueError):
            raise CommandError("Invalid native profile UUID.") from None
        profiles = {str(p.pk): p for p in SlicerProfile.objects.filter(pk__in=ids)}
        if len(profiles) != len(set(ids)):
            raise CommandError("Selected native profiles unavailable.")
        machine_record, process_record, *filament_records = [
            profiles[str(identity)] for identity in ids
        ]
        version = machine_record.engine_version
        owner = machine_record.owner_id
        if (version != "7.3.1" or
                not _same_native_pair(machine_record, owner, "crealityprint", version, "printer") or
                not _same_native_pair(process_record, owner, "crealityprint", version, "process") or
                any(not _same_native_pair(p, owner, "crealityprint", version, "filament")
                    for p in filament_records)):
            raise CommandError("Profiles must be owned Creality Print 7.3.1 candidates from one account.")
        native = [resolved_native_profile(p) for p in
                  (machine_record, process_record, *filament_records)]
        for kind, blob in zip(("printer", "process", "filament", "filament"), native):
            check_native_compatibility("crealityprint", version, kind, blob)
        if _native_nozzle_count(native[0]) != 1:
            raise CommandError("Synthetic two-colour test requires one native nozzle.")
        width, depth = trusted_plate_dimensions(machine_record)
        engine = verified_installation().get("crealityprint")
        if not engine or engine["version"] != version:
            raise CommandError("Approved Creality 7.3.1 worker unavailable.")
        source = _cantilever_fixture_stl()
        scenario_names = ["baseline", options["only"]] if options["only"] else list(CASES)
        results = {}
        baseline = None
        for feature in scenario_names:
            try:
                project, process_blob = _fixture_project(
                    source, feature, machine=native[0], process=native[1],
                    filaments=native[2:], width=width, depth=depth)
                def run(blob):
                    return run_remote_job(
                        uuid.uuid4(), "crealityprint", version, blob,
                        native[0], native[2], process_blob,
                        model_format="3mf", filament_profiles=native[2:],
                        creality_native_project=True, timeout_seconds=900)
                data = run(project)
                _approved_gcode(data)
                metrics = _metrics(data)
                output = {
                    "status": "sliced",
                    "motion_sha256": metrics["motion_sha256"],
                    "tool0_selects": metrics["tool0_selects"],
                    "tool1_selects": metrics["tool1_selects"],
                    "extrusion_moves": metrics["g1_with_extrusion"],
                    "feature_role_audit": _feature_role_audit(data),
                    "flush_audit": {
                        key: value for key, value in
                        _creality_toolchange_macro_audit(data).items()
                        if key in (
                            "flush_start_comment_count", "flush_end_comment_count",
                            "flush_markers_balanced", "completed_flush_sections",
                            "m8200_command_count",
                            "positive_extrusion_only_flush_length_mm",
                            "extrusion_modes_observed_in_flush",
                            "unclassified_flush_g1_e_moves",
                        )
                    },
                }
                if feature == "baseline":
                    colour_bounds = painted_triangle_bounds(project, "paint_color")
                    colour_usage = spatial_deposition_cells(
                        data, bounds=colour_bounds, tool=1)
                    output["colour_spatial_observation"] = {
                        "painted_tag_bounds_mm": colour_bounds,
                        "tool1_deposition_moves_in_painted_xy": (
                            colour_usage["inside_painted_xy_moves"]),
                        "tool1_deposition_moves_outside_painted_xy": (
                            colour_usage["outside_painted_xy_moves"]),
                        "tool1_spatial_presence_observed": (
                            colour_usage["inside_painted_xy_moves"] > 0),
                        "limitations": (
                            "Native tool ID is a logical filament, not a CFS bay. "
                            "Spatial presence is not proof of exact painted boundaries."),
                    }
                if feature == "variable":
                    output["observed_layer_steps_mm"] = metrics[
                        "observed_layer_steps_mm"]
                    output["requested_0_12mm_layer_step_observed"] = (
                        0.12 in metrics["observed_layer_steps_mm"])
                if feature == "flushing":
                    # Stock K2 multicolor_method absent/disabled must remain
                    # distinguishable from activated native purge; a successful
                    # slice alone is not a successful flushing test.
                    flush_audit = _creality_toolchange_macro_audit(data)
                    output["native_flush_effect_observed"] = (
                        flush_audit["completed_flush_sections"] > 0
                        and flush_audit["m8200_command_count"] > 0
                        and flush_audit["flush_markers_balanced"])
                    output["inactive_machine_gate_expected"] = (
                        str(json.loads(native[0]).get(
                            "multicolor_method", "0")) == "0")
                if feature == "baseline":
                    baseline = metrics
                else:
                    output["motion_changed_from_baseline"] = (
                        metrics["motion_sha256"] != baseline["motion_sha256"])
                if feature in ("support", "seam", "fuzzy") and options["deep"]:
                    control, count = _geometry_control_project(project, feature)
                    control_data = run(control)
                    _approved_gcode(control_data)
                    control_metrics = _metrics(control_data)
                    output["same_geometry_control"] = {
                        "removed_semantic_paint_triangles": count,
                        "motion_changed": (
                            control_metrics["motion_sha256"] != metrics["motion_sha256"]),
                        "extrusion_move_difference": (
                            metrics["g1_with_extrusion"] -
                            control_metrics["g1_with_extrusion"]),
                    }
                    attribute = {
                        "support": "paint_supports",
                        "seam": "paint_seam",
                        "fuzzy": "paint_fuzzy_skin",
                    }[feature]
                    bounds = painted_triangle_bounds(project, attribute)
                    output["spatial_geometry_control"] = spatial_comparison(
                        data, control_data, bounds,
                        role="support" if feature == "support" else "outer_wall",
                    )
                results[feature] = output
            except Exception as exc:
                # Error summaries are bounded and deliberately omit raw private
                # native profiles, macros, G-code and file paths.
                results[feature] = {
                    "status": "failed", "error_class": type(exc).__name__,
                    "note": "Review application logs for the failed offline fixture.",
                }
                if feature == "baseline":
                    break
        self.stdout.write(json.dumps({
            "schema": 1, "engine": version, "offline_only": True,
            "printer_dispatch_approved": False,
            "fixture": "synthetic-two-colour-cantilever",
            "cases": results,
            "note": ("Synthetic native geometry, not a user job. Changed G-code "
                     "does not prove paint effect or printer safety."),
        }, indent=2))
