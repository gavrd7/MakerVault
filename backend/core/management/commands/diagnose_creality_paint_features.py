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
import io
import zipfile
import struct
from xml.etree import ElementTree as ET

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
_SEMANTIC_ATTRS = {
    "support": "paint_supports",
    "seam": "paint_seam",
    "fuzzy": "paint_fuzzy_skin",
}
_CORE_NS = "{http://schemas.microsoft.com/3dmanufacturing/core/2015/02}"


def _geometry_control_project(project, feature):
    """Keep *identical* remeshed triangles, colours and native presets.

    Remove only the semantic paint attribute being measured. A native slice
    of this control is the appropriate comparator, not the original mesh
    whose triangulation changes when a brush patch is applied.
    """
    attribute = _SEMANTIC_ATTRS[feature]
    result = io.BytesIO()
    removed = 0
    with zipfile.ZipFile(io.BytesIO(project)) as source, zipfile.ZipFile(
            result, "w", compression=zipfile.ZIP_DEFLATED,
            allowZip64=False) as output:
        for info in source.infolist():
            body = source.read(info.filename)
            if info.filename == "3D/3dmodel.model":
                root = ET.fromstring(body)
                for triangle in root.iter(_CORE_NS + "triangle"):
                    if attribute in triangle.attrib:
                        triangle.attrib.pop(attribute)
                        removed += 1
                body = ET.tostring(root, encoding="utf-8", xml_declaration=True)
            output.writestr(info.filename, body)
    if not removed:
        raise ValueError("Diagnostic patch produced no native painted facets.")
    return result.getvalue(), removed


def _layer_band_audit(gcode, lower, upper, *, target=0.12):
    """Count actual consecutive layer steps within a requested Z interval."""
    if not isinstance(gcode, bytes):
        raise ValueError("Invalid native toolpath")
    zs = [float(x) for x in re.findall(
        rb"(?im)^;Z:\s*([0-9]+(?:\.[0-9]+)?)\s*$", gcode)]
    unique = sorted(set(round(z, 4) for z in zs))
    inside = []
    outside = []
    for a, b in zip(unique, unique[1:]):
        step = round(b - a, 3)
        if not 0.049 <= step <= 0.501:
            continue
        # Only count a step as inside when both layer boundaries are inside.
        (inside if lower <= a and b <= upper else outside).append(step)
    return {
        "requested_band_mm": [lower, upper],
        "requested_step_mm": target,
        "interior_steps": len(inside),
        "interior_target_steps": sum(abs(step - target) <= 0.002 for step in inside),
        "interior_observed_steps_mm": sorted(set(inside))[:24],
        "outside_observed_steps_mm": sorted(set(outside))[:24],
        "band_target_observed": any(abs(step - target) <= 0.002 for step in inside),
    }



def _native_project_audit(package):
    """Read only bounded non-sensitive effective settings from the generated 3MF."""
    with zipfile.ZipFile(io.BytesIO(package)) as archive:
        values = json.loads(archive.read("Metadata/project_settings.config"))
    audit = {
        "support_enabled": str(values.get("enable_support", "")),
        "support_type": str(values.get("support_type", ""))[:48],
        "fuzzy_skin": str(values.get("fuzzy_skin", ""))[:48],
        "seam_position": str(values.get("seam_position", ""))[:48],
        # Creality 7.3.1 uses distinct wipe-tower and filament-change paths.
        "enable_prime_tower": str(values.get("enable_prime_tower", ""))[:12],
        "purge_in_prime_tower": str(values.get("purge_in_prime_tower", ""))[:12],
        "single_extruder_multi_material": str(
            values.get("single_extruder_multi_material", ""))[:12],
        "multicolor_method": str(values.get("multicolor_method", ""))[:12],
        "prime_volume_mm3": str(values.get("prime_volume", ""))[:24],
        # Do not disclose native printer/profile macros.
        "has_change_filament_gcode": bool(values.get("change_filament_gcode")),
        "change_gcode_uses_flush_length": (
            "flush_length" in str(values.get("change_filament_gcode", ""))),

    }
    matrix = values.get("flush_volumes_matrix")
    multiplier = values.get("flush_multiplier")
    if isinstance(matrix, list) and len(matrix) == 16:
        try:
            raw_01, raw_10 = float(matrix[1]), float(matrix[4])
            factor = float(multiplier) if multiplier is not None else 1.0
            if all(math.isfinite(v) for v in (raw_01, raw_10, factor)):
                audit["flush_t0_to_t1_mm3"] = round(raw_01 * factor, 3)
                audit["flush_t1_to_t0_mm3"] = round(raw_10 * factor, 3)
        except (ValueError, TypeError):
            pass
    audit["flush_volumes_changed"] = str(values.get("flush_volumes_changed", ""))
    return audit


def _gcode_effective_settings(gcode):
    """Read safe config comments emitted by Creality GCode.cpp.

    Presence of a value in G-code comments is not evidence of its
    physical execution. Missing keys are reported by omission.
    """
    if not isinstance(gcode, bytes) or len(gcode) > 64 * 1024 * 1024:
        raise ValueError("Invalid diagnostic G-code")
    safe_keys = (
        "enable_prime_tower", "purge_in_prime_tower", "prime_volume",
        "flush_multiplier", "flush_volumes_changed", "multicolor_method",
        "single_extruder_multi_material",
    )
    found = {}
    for key in safe_keys:
        match = re.search(
            rb"(?im)^;\\s*" + key.encode("ascii") + rb"\\s*=\\s*([^\\r\\n]{0,40})",
            gcode)
        if match:
            found[key] = match.group(1).decode("ascii", errors="replace").strip()
    # Do not expose the complete matrix in case the native footer changes
    # format. A digest is sufficient to compare baseline vs override.
    match = re.search(rb"(?im)^;\\s*flush_volumes_matrix\\s*=\\s*([^\\r\\n]{0,4096})", gcode)
    if match:
        found["flush_matrix_gcode_header_sha256"] = hashlib.sha256(
            match.group(1).strip()).hexdigest()
    return found


def _feature_role_audit(gcode):
    """Count extrusion moves by native FEATURE/TYPE role, not generic comments.

    Creality GCode.cpp emits extrusion-role tags through GCodeProcessor.
    An actual support test must show support-role extrusion, not merely a
    different hash or an enabled support checkbox.
    """
    if not isinstance(gcode, bytes) or len(gcode) > 64 * 1024 * 1024:
        raise ValueError("Invalid diagnostic G-code")
    role = ""
    counts = {"support": 0, "outer_wall": 0, "other": 0}
    role_tags = 0
    for line in gcode.splitlines():
        tag = re.match(rb"^;\\s*(?:FEATURE|TYPE)\\s*:\\s*(.{1,60})$", line, re.I)
        if tag:
            role = tag.group(1).decode("ascii", errors="replace").lower().strip()
            role_tags += 1
            continue
        command = line.partition(b";")[0].strip().upper()
        if (re.match(rb"^G0?1(?:\\s|$)", command) and
                re.search(rb"(?:^|\\s)E[-+]?\\d", command) and
                (re.search(rb"(?:^|\\s)X[-+]?\\d", command) or
                 re.search(rb"(?:^|\\s)Y[-+]?\\d", command))):
            bucket = ("support" if "support" in role else
                      "outer_wall" if any(term in role for term in
                                          ("outer wall", "external perimeter")) else "other")
            counts[bucket] += 1
    return {"feature_role_tags": role_tags, "extrusion_xy_moves_by_role": counts}


def _cantilever_fixture_stl():
    """Watertight, offline-only L-section cantilever: 30 x 12 x 25 mm.

    The elevated underside spans X=10..30, Z=20, above empty space.
    Unlike the original colour cube, it can demand painted support.
    """
    outline = [(0., 0.), (10., 0.), (10., 20.),
               (30., 20.), (30., 25.), (0., 25.)]
    caps = ((0, 1, 2), (0, 2, 5), (2, 3, 4), (2, 4, 5))
    triangles = []
    for a, b, c in caps:
        for y, ids in ((0., (a, b, c)), (12., (c, b, a))):
            triangles.append(tuple((outline[i][0], y, outline[i][1]) for i in ids))
    for i in range(len(outline)):
        a, b = outline[i], outline[(i + 1) % len(outline)]
        a0, b0 = (a[0], 0., a[1]), (b[0], 0., b[1])
        a1, b1 = (a[0], 12., a[1]), (b[0], 12., b[1])
        triangles.extend(((a0, b1, b0), (a0, a1, b1)))
    data = bytearray(b"MakerVault offline diagnostic cantilever".ljust(80, b"\\x00"))
    data.extend(struct.pack("<I", len(triangles)))
    for tri in triangles:
        data.extend(struct.pack("<12fH", *([0.] * 3),
                                *(coord for vertex in tri for coord in vertex), 0))
    return bytes(data)


def _cantilever_support_marker(stl):
    """Paint the suspended downward face, never the build-plate underside."""
    tris = list(_triangles(stl))
    signature, _unused, _unused_poly, _height = _patch_for_model(stl)
    min_x = min(v[0] for tri in tris for v in tri)
    max_x = max(v[0] for tri in tris for v in tri)
    min_y = min(v[1] for tri in tris for v in tri)
    max_y = max(v[1] for tri in tris for v in tri)
    min_z = min(v[2] for tri in tris for v in tri)
    origin = ((min_x + max_x) / 2, (min_y + max_y) / 2, min_z)
    for idx, tri in enumerate(tris):
        if (all(abs(p[2] - 20.) < 1e-5 for p in tri) and
                sum(p[0] for p in tri) / 3 > 13.):
            a, b, c = tri
            ux = (b[0] - a[0], b[1] - a[1])
            vx = (c[0] - a[0], c[1] - a[1])
            z_normal = ux[0]*vx[1] - ux[1]*vx[0]
            if z_normal >= 0:
                continue
            centre = [sum(p[axis] for p in tri) / 3 for axis in range(3)]
            polygon = [
                [(0.9 * vertex[axis] + 0.1 * centre[axis]) - origin[axis]
                 for axis in range(3)]
                for vertex in tri
            ]
            return {"version": 2, "signature": signature, "regions": [
                {"slot": 0, "patches": [{"face": idx, "polygon": polygon}]}
            ]}
    raise ValueError("The diagnostic cantilever has no exposed elevated underside.")


def _cantilever_wall_marker(stl):
    """Target a broad, outer vertical wall for seam/fuzzy geometry controls."""
    tris = list(_triangles(stl))
    signature, _face, _polygon, _height = _patch_for_model(stl)
    minima = [min(point[i] for tri in tris for point in tri) for i in range(3)]
    maxima = [max(point[i] for tri in tris for point in tri) for i in range(3)]
    origin = ((minima[0] + maxima[0]) / 2,
              (minima[1] + maxima[1]) / 2, minima[2])
    for idx, tri in enumerate(tris):
        zs = [p[2] for p in tri]
        if all(abs(p[1]) < 1e-5 for p in tri) and max(zs) - min(zs) > 15:
            centre = [sum(p[axis] for p in tri) / 3 for axis in range(3)]
            polygon = [
                [(0.9 * point[axis] + 0.1 * centre[axis]) - origin[axis]
                 for axis in range(3)]
                for point in tri
            ]
            return {"version": 2, "signature": signature, "regions": [
                {"slot": 0, "patches": [{"face": idx, "polygon": polygon}]}
            ]}
    raise ValueError("Diagnostic cantilever has no broad exterior wall.")


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
    # Ignore headers, timestamps and metadata. Compare actual motion and
    # tool-selection commands, not the byte hash of entire G-code files.
    motion_digest = hashlib.sha256()
    machine_digest = hashlib.sha256()
    for line in text.splitlines():
        command = line.partition(";")[0].strip()
        if re.match(r"^(?:G0?[0123]|T[01])(?:\s|$)", command, re.I):
            motion_digest.update(" ".join(command.upper().split()).encode("utf-8"))
            motion_digest.update(b"\n")
        elif re.match(r"^M\d+(?:\s|$)", command, re.I):
            machine_digest.update(" ".join(command.upper().split()).encode("utf-8"))
            machine_digest.update(b"\n")
    zs = [float(x) for x in re.findall(r"(?im)^;Z:\s*([0-9]+(?:\.[0-9]+)?)\s*$", text)]
    layers = sorted(set(round(x, 4) for x in zs))
    steps = sorted(set(round(b-a, 3) for a,b in zip(layers,layers[1:])
                       if .049 <= b-a <= .501))
    return {
        "gcode_sha256": hashlib.sha256(gcode).hexdigest(),
        "motion_sha256": motion_digest.hexdigest(),
        "machine_command_sha256": machine_digest.hexdigest(),
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
        parser.add_argument("--deep", action="store_true", help="Also slice identical-geometry unpainted controls for semantic facets")
        parser.add_argument("--support-fixture", action="store_true",
                            help="Replace the in-memory support test mesh with a fixed unsupported cantilever")
        parser.add_argument("--wall-fixture", action="store_true",
                            help="Use a synthetic outside wall for seam or fuzzy tests")

    def handle(self, *args, **options):
        if options["support_fixture"] and (
                options["only"] != "support" or not options["deep"]):
            raise CommandError("--support-fixture requires --only support --deep.")
        if options["wall_fixture"] and (
                options["only"] not in ("seam", "fuzzy") or not options["deep"]):
            raise CommandError("--wall-fixture requires --only seam|fuzzy --deep.")

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
            model_stl = raw_stl
            synthetic_fixture = (
                (feature == "support" and options["support_fixture"]) or
                (feature in ("seam", "fuzzy") and options["wall_fixture"]))
            if synthetic_fixture:
                # Explicit synthetic test only; no FileAsset, saved job, or
                # private mesh is changed. Preserve the user's known-good
                # verified two-slot material palette and native profiles.
                model_stl = _cantilever_fixture_stl()
                colour_signature, colour_face, colour_polygon, _ = _patch_for_model(model_stl)
                old_colour = obj["colour_paint"]
                base_slot_id = (obj.get("material_slot") or {}).get("slot_id")
                first_colour_region = next((
                    region for region in old_colour["regions"]
                    if old_colour["palette"][region["slot"]].get("slot_id") != base_slot_id
                ), old_colour["regions"][0])
                obj["colour_paint"] = {
                    "version": 2, "signature": colour_signature,
                    "palette": copy.deepcopy(old_colour["palette"]),
                    "regions": [{"slot": first_colour_region["slot"],
                                 "patches": [{"face": colour_face,
                                              "polygon": colour_polygon}]}],
                }
                if feature == "support":
                    obj["support_paint"] = _cantilever_support_marker(model_stl)
                elif feature == "seam":
                    obj["seam_paint"] = _cantilever_wall_marker(model_stl)
                else:
                    obj["fuzzy_skin_paint"] = _cantilever_wall_marker(model_stl)
            # Deliberately change only native flush values in this test case.
            copy_settings["flush_settings"] = None
            job.settings = copy_settings  # In-memory only: NEVER call .save().
            try:
                prepared = prepare_creality_positioned_project(
                    job, [(obj, model_stl)], bed_width=width, bed_depth=depth)
                first = prepared["filament_profiles"][0]
                process, first = apply_creality_plate(
                    process_native, first, job.plate,
                    printer_profile=job.printer_profile)
                if feature == "support":
                    # Diagnostic-only manual supports test: no user preset mutation.
                    native = json.loads(process)
                    native["enable_support"] = "1"
                    native["support_type"] = "normal(manual)"
                    process = json.dumps(native, separators=(",", ":")).encode("utf-8")
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
                audit = _native_project_audit(package)
                data = run_remote_job(
                    uuid.uuid4(), "crealityprint", job.engine_version,
                    package, printer_native, prepared["filament_profiles"][0], process,
                    model_format="3mf", filament_profiles=prepared["filament_profiles"],
                    creality_native_project=True, timeout_seconds=900)
                metrics = _metrics(data)
                if synthetic_fixture:
                    metrics["test_geometry"] = (
                        "synthetic elevated cantilever (offline only)" if feature == "support"
                        else "synthetic exterior wall (offline only)")
                metrics["gcode_effective_settings"] = _gcode_effective_settings(data)
                metrics["feature_role_audit"] = _feature_role_audit(data)
                if feature == "variable":
                    metrics["layer_band_audit"] = _layer_band_audit(data, lo, hi)
                if feature in _SEMANTIC_ATTRS and options["deep"]:
                    # Same STL triangulation, process and colour annotations;
                    # the only removed input is this semantic facet channel.
                    control, painted_facets = _geometry_control_project(package, feature)
                    control_data = run_remote_job(
                        uuid.uuid4(), "crealityprint", job.engine_version,
                        control, printer_native, prepared["filament_profiles"][0], process,
                        model_format="3mf", filament_profiles=prepared["filament_profiles"],
                        creality_native_project=True, timeout_seconds=900)
                    control_metrics = _metrics(control_data)
                    control_role_audit = _feature_role_audit(control_data)
                    metrics["geometry_control"] = {
                        "removed_semantic_facets": painted_facets,
                        "motion_changed_from_same_geometry": (
                            metrics["motion_sha256"] != control_metrics["motion_sha256"]),
                        "machine_commands_changed_from_same_geometry": (
                            metrics["machine_command_sha256"] != control_metrics["machine_command_sha256"]),
                        "extrusion_command_difference": (
                            metrics["g1_with_extrusion"] - control_metrics["g1_with_extrusion"]),
                        "support_xy_move_difference": (
                            metrics["feature_role_audit"]["extrusion_xy_moves_by_role"]["support"] -
                            control_role_audit["extrusion_xy_moves_by_role"]["support"]),
                        "note": "Same triangulation, colours and process; only semantic paint attribute removed.",
                    }
                if feature == "baseline":
                    baseline = metrics
                else:
                    metrics["toolpath_changed_from_baseline"] = (
                        metrics["motion_sha256"] != baseline["motion_sha256"])
                    metrics["machine_commands_changed_from_baseline"] = (
                        metrics["machine_command_sha256"] != baseline["machine_command_sha256"])
                    current_matrix = metrics["gcode_effective_settings"].get(
                        "flush_matrix_gcode_header_sha256")
                    previous_matrix = baseline["gcode_effective_settings"].get(
                        "flush_matrix_gcode_header_sha256")
                    if current_matrix and previous_matrix:
                        metrics["gcode_header_flush_matrix_changed"] = (
                            current_matrix != previous_matrix)
                    if feature in _SEMANTIC_ATTRS and "geometry_control" in metrics:
                        metrics["observation"] = (
                            "Semantic attribute changes motion relative to identical remeshed geometry; spatial effect still needs review."
                            if metrics["geometry_control"]["motion_changed_from_same_geometry"]
                            else "No semantic facet motion effect observed against identical geometry control.")
                    else:
                        metrics["observation"] = (
                            "Changed G-code; specific painting effect still needs toolpath audit."
                            if metrics["toolpath_changed_from_baseline"]
                            else "No motion difference; native effect not demonstrated.")
                results[feature] = {"status": "sliced", "native_settings": audit, **metrics}
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
