"""Generate and slice fixed two-material Bambu 3MF acceptance fixtures.

No printer control, network access, arbitrary paths inside the worker or
external model/profile data is embedded. Verify real tool deposition instead
of treating a successfully opened project as a multicolour slicing pass.
"""
import argparse
import hashlib
import io
import json
import tempfile
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

from slicer_worker.bambu_runner import run_bambu
from slicer_worker.material_gcode_audit import (
    expected_native_tools, verify_multi_material_output,
    verify_two_object_tool_regions, verify_painted_cube_tool_regions,
    summarize_k2_fixture_changeovers,
)
from slicer_worker.runner import WorkerError
from slicer_worker.three_mf_validation import CORE_NS, validate_worker_3mf


def make_bambu_material_fixture(*, painted=False, native_app=True,
                                variable_layers=False, detail_paint=None):
    """Build 1 painted cube or 2 separately assigned cubes on a 256mm plate."""
    if detail_paint not in (None, "support", "seam", "fuzzy", "combined"):
        raise WorkerError("Unsupported native Bambu semantic paint fixture.")
    if detail_paint is not None and not painted:
        raise WorkerError("Bambu semantic paint fixture requires a painted model.")
    if variable_layers and not painted:
        raise WorkerError("Bambu variable-layer fixture requires one painted object.")
    ns = "{" + CORE_NS + "}"
    ET.register_namespace("", CORE_NS)
    model = ET.Element(ns + "model", {"unit": "millimeter"})
    if native_app:
        # CI-only hypothesis: upstream only loads vendor object metadata if
        # the source declares a BambuStudio-compatible application marker.
        ET.SubElement(model, ns + "metadata",
                      {"name": "Application"}).text = "BambuStudio-02.09.01.70"
        ET.SubElement(model, ns + "metadata",
                      {"name": "BambuStudio:3mfVersion"}).text = "1"
    resources = ET.SubElement(model, ns + "resources")
    build = ET.SubElement(model, ns + "build")
    # X positions deliberately match the existing material/deposition audit.
    positions = [(75, 110)] if painted else [(75, 110), (145, 110)]
    vertices = [
        (-10, -10, 0), (10, -10, 0), (10, 10, 0), (-10, 10, 0),
        (-10, -10, 20), (10, -10, 20), (10, 10, 20), (-10, 10, 20),
    ]
    faces = (
        (0, 2, 1), (0, 3, 2), (4, 5, 6), (4, 6, 7),
        (0, 1, 5), (0, 5, 4), (1, 2, 6), (1, 6, 5),
        (2, 3, 7), (2, 7, 6), (3, 0, 4), (3, 4, 7),
    )
    manifest = ET.Element("config")
    for index, (x, y) in enumerate(positions, 1):
        obj = ET.SubElement(resources, ns + "object", {"id": str(index), "type": "model"})
        mesh = ET.SubElement(obj, ns + "mesh")
        points = ET.SubElement(mesh, ns + "vertices")
        for dx, dy, z in vertices:
            ET.SubElement(points, ns + "vertex", {
                "x": str(x + dx), "y": str(y + dy), "z": str(z)})
        triangles = ET.SubElement(mesh, ns + "triangles")
        for face_index, (v1, v2, v3) in enumerate(faces):
            attrs = {"v1": str(v1), "v2": str(v2), "v3": str(v3)}
            if painted and face_index in (2, 3, 6, 7):
                # Native 3MF TriangleSelector state: paint_color=8 => tool 1.
                attrs["paint_color"] = "8"
            if painted and detail_paint is not None and face_index in (2, 3, 6, 7):
                # Additional native TriangleSelector states on those same
                # tessellated model regions. No geometry modification.
                for mode, native_attribute in (
                        ("support", "paint_supports"),
                        ("seam", "paint_seam"),
                        ("fuzzy", "paint_fuzzy_skin")):
                    if detail_paint in (mode, "combined"):
                        attrs[native_attribute] = "4"
            ET.SubElement(triangles, ns + "triangle", attrs)
        ET.SubElement(build, ns + "item", {
            "objectid": str(index),
            "transform": "1 0 0 0 1 0 0 0 1 0 0 0"})
        item = ET.SubElement(manifest, "object", {"id": str(index)})
        ET.SubElement(item, "metadata", {
            "key": "extruder", "value": str(1 if painted else index)})
    plate = ET.SubElement(manifest, "plate")
    ET.SubElement(plate, "metadata", {"key": "plater_id", "value": "1"})
    for index in range(1, len(positions) + 1):
        item = ET.SubElement(plate, "model_instance")
        for name, value in (("object_id", str(index)), ("instance_id", "0"),
                            ("identify_id", str(index))):
            ET.SubElement(item, "metadata", {"key": name, "value": value})
    content_types = (
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="model" ContentType="application/vnd.ms-package.3dmanufacturing-3dmodel+xml"/>'
        '</Types>')
    rels = (
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rel0" Target="/3D/3dmodel.model" '
        'Type="http://schemas.microsoft.com/3dmanufacturing/2013/01/3dmodel"/>'
        '</Relationships>')
    with io.BytesIO() as data:
        with zipfile.ZipFile(data, "w", compression=zipfile.ZIP_DEFLATED) as package:
            package.writestr("3D/3dmodel.model", ET.tostring(model, encoding="utf-8"))
            package.writestr("Metadata/model_settings.config",
                             ET.tostring(manifest, encoding="utf-8"))
            if variable_layers:
                # BambuStudio 2.9.1 native bbs_3mf.cpp imports the same
                # Metadata/layer_config_ranges.xml structure as Orca.
                ranges = ET.Element("objects")
                target = ET.SubElement(ranges, "object", {"id": "1"})
                for start, stop, height in (
                        ("0.0", "9.0", "0.10"),
                        ("9.0", "20.0", "0.30")):
                    band = ET.SubElement(target, "range",
                                         {"min_z": start, "max_z": stop})
                    ET.SubElement(band, "option",
                                  {"opt_key": "layer_height"}).text = height
                package.writestr("Metadata/layer_config_ranges.xml",
                                 ET.tostring(ranges, encoding="utf-8"))
            # Bambu CLI 02.09.01.70 reads these project vectors during
            # --export-3mf; absent filament IDs can abort inside upstream
            # get_at(). A generic core 3MF is sufficient only for one tool.
            package.writestr("Metadata/project_settings.config", json.dumps({
                "printer_settings_id": "Bambu Lab X1 Carbon 0.4 nozzle",
                "print_settings_id": "0.20mm Standard @BBL X1C",
                "filament_settings_id": ["MakerVault PLA Tool 1", "MakerVault PLA Tool 2"],
                "filament_colour": ["#FFFF00", "#0000FF"],
                "filament_type": ["PLA", "PLA"],
                "filament_diameter": ["1.75", "1.75"],
                "filament_ids": ["GFA00", "GFA00"],
                "filament_is_support": ["0", "0"],
                "filament_flow_ratio": ["0.98"] * 4,
                "nozzle_temperature": ["220"] * 4,
                "nozzle_temperature_initial_layer": ["220"] * 4,
                "filament_max_volumetric_speed": ["21", "29", "21", "29"],
                "filament_retraction_length": ["nil", "0.4", "nil", "0.4"],
                "filament_self_index": ["1", "1", "2", "2"],
                "filament_extruder_variant": [
                    "Direct Drive Standard", "Direct Drive High Flow",
                    "Direct Drive Standard", "Direct Drive High Flow"],

                "nozzle_diameter": ["0.4"],
                "printable_height": "256",
            }, separators=(",", ":")))
            package.writestr("[Content_Types].xml", content_types)
            package.writestr("_rels/.rels", rels)
        raw = data.getvalue()
    validate_worker_3mf(raw, native_tool_count=2, allow_bambu_project=True,
                        allow_bambu_combined_paint=painted,
                        allow_bambu_layer_ranges=variable_layers)
    if expected_native_tools(raw) != {0, 1}:
        raise WorkerError("Two-material fixture did not select both logical tools.")
    return raw


def run_fixture(binary, profiles, *, painted=False, timeout=180,
                flush_multiplier=None, tower_xy=None, variable_layers=False,
                detail_paint=None):
    source = Path(profiles)
    with tempfile.TemporaryDirectory(prefix="makervault-bambu-two-tool-") as tmp:
        workdir = Path(tmp)
        project = make_bambu_material_fixture(painted=painted,
                                              variable_layers=variable_layers,
                                              detail_paint=detail_paint)
        (workdir / "input.3mf").write_bytes(project)
        for kind in ("printer", "process", "filament"):
            raw = (source / (kind + ".json")).read_bytes()
            (workdir / (kind + ".json")).write_bytes(raw)
        if flush_multiplier is not None or tower_xy is not None:
            # CI-only exact native process settings: production uses
            # apply_orca_flush_settings/apply_bambu_prime_tower_position.
            process_doc = json.loads((workdir / "process.json").read_bytes())
            if flush_multiplier is not None:
                if flush_multiplier not in (1.0, 2.0):
                    raise WorkerError("Unsupported Bambu flush evidence multiplier.")
                process_doc["flush_multiplier"] = [str(flush_multiplier)]
            if tower_xy is not None:
                x, y = tower_xy
                if not (5 <= x <= 220 and 5 <= y <= 220):
                    raise WorkerError("Invalid Bambu fixture tower XY.")
                process_doc["wipe_tower_x"] = [str(x)]
                process_doc["wipe_tower_y"] = [str(y)]
            (workdir / "process.json").write_text(
                json.dumps(process_doc, ensure_ascii=False, separators=(",", ":")))
        filament = json.loads((workdir / "filament.json").read_bytes())
        # Both slots use authentic, fully resolved BBL PLA parameters, but
        # distinct job-local names prevent Bambu 2.9.1's duplicate-preset
        # special mapping from conflating logical tool 0 with tool 1.
        for index in range(2):
            entry = dict(filament)
            entry["name"] = "MakerVault PLA Tool " + str(index + 1)
            entry["filament_settings_id"] = [entry["name"]]
            (workdir / ("filament-" + str(index) + ".json")).write_text(
                json.dumps(entry, ensure_ascii=False, separators=(",", ":")))
        (workdir / "filament.json").write_bytes(
            (workdir / "filament-0.json").read_bytes())
        try:
            receipt = run_bambu(Path(binary), workdir, timeout_seconds=timeout)
        except WorkerError:
            # Diagnostic only: this invocation is an ephemeral CI fixture
            # using public, pinned BBL profiles and a synthetic 3MF. Never
            # expose native stderr from production worker requests.
            import os
            if os.environ.get("MAKERVAULT_BAMBU_FIXTURE_DIAGNOSTICS") == "1":
                import subprocess
                from slicer_worker.bambu_runner import bambu_command
                from slicer_worker.headless_env import slicing_environment
                args = bambu_command(Path(binary), workdir)
                prefix = args[:args.index("--slice")]
                model = str(workdir / "input.3mf")
                # Compare the real Bambu CLI's plate numbering and export
                # path. Every test has a separate scratch output; no printer
                # API/credentials and no production data are involved.
                tagged_model = workdir / "tagged.3mf"
                tagged_model.write_bytes(make_bambu_material_fixture(
                    painted=painted, native_app=True))
                validate_worker_3mf(tagged_model.read_bytes(),
                    native_tool_count=2, allow_bambu_project=True)
                variants = [
                    ("slice0_export", ["--slice", "0", "--export-3mf",
                                      str(workdir / "bambu-debug-0.3mf"), model]),
                    ("slice1_export", ["--slice", "1", "--export-3mf",
                                      str(workdir / "bambu-debug-1.3mf"), model]),
                    ("slice1_output", ["--slice", "1", "--outputdir",
                                      str(workdir / "bambu-debug-out"), model]),

                    ("no_overrides", ["--slice", "0", "--outputdir",
                                      str(workdir / "no-overrides"), model]),
                    ("machine_process_only", [
                        "--load-settings", str(workdir / "printer.json") + ";" +
                        str(workdir / "process.json"), "--slice", "0",
                        "--outputdir", str(workdir / "machine-process-only"), model]),
                    ("filaments_only", [
                        "--load-filaments", str(workdir / "filament-0.json") + ";" +
                        str(workdir / "filament-1.json"), "--slice", "0",
                        "--outputdir", str(workdir / "filaments-only"), model]),
                    ("filament0_one_only", [
                        "--load-filaments", str(workdir / "filament-0.json"),
                        "--slice", "0", "--outputdir",
                        str(workdir / "filament0-one-only"), model]),
                    ("filament0_blank_second", [
                        "--load-filaments", str(workdir / "filament-0.json") + ";",
                        "--slice", "0", "--outputdir",
                        str(workdir / "filament0-blank-second"), model]),
                    ("blank_first_filament1", [
                        "--load-filaments", ";" + str(workdir / "filament-1.json"),
                        "--slice", "0", "--outputdir",
                        str(workdir / "blank-first-filament1"), model]),
                    ("tagged_no_overrides", [
                        "--slice", "0", "--outputdir",
                        str(workdir / "tagged-no-overrides"), str(tagged_model)]),
                    ("tagged_machine_process_only", [
                        "--load-settings", str(workdir / "printer.json") + ";" +
                        str(workdir / "process.json"),
                        "--slice", "0", "--outputdir",
                        str(workdir / "tagged-machine-process-only"), str(tagged_model)]),
                    ("tagged_filaments_only", [
                        "--load-filaments", str(workdir / "filament-0.json") + ";" +
                        str(workdir / "filament-1.json"),
                        "--slice", "0", "--outputdir",
                        str(workdir / "tagged-filaments-only"), str(tagged_model)]),
                    ("tagged_machine_process_export", [
                        "--load-settings", str(workdir / "printer.json") + ";" +
                        str(workdir / "process.json"),
                        "--slice", "0", "--export-3mf",
                        str(workdir / "tagged-sliced.3mf"), str(tagged_model)]),
                    ("tagged_machine_process_one_filament", [
                        "--load-settings", str(workdir / "printer.json") + ";" +
                        str(workdir / "process.json"),
                        "--load-filaments", str(workdir / "filament-0.json"),
                        "--slice", "0", "--outputdir",
                        str(workdir / "tagged-machine-process-one-filament"), str(tagged_model)]),
                ]
                for label, tail in variants:
                    try:
                        selected_prefix = ([str(binary)] if label in (
                            "no_overrides", "machine_process_only", "filaments_only",
                            "filament0_one_only", "filament0_blank_second",
                            "blank_first_filament1", "tagged_no_overrides",
                            "tagged_machine_process_only", "tagged_filaments_only",
                            "tagged_machine_process_export",
                            "tagged_machine_process_one_filament")
                            else prefix)
                        attempt = subprocess.run(selected_prefix + tail, cwd=workdir,
                            env={**slicing_environment(workdir),
                                 "SSL_CERT_FILE": "/etc/ssl/certs/ca-certificates.crt"},
                            stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, timeout=min(timeout, 60), check=False)
                    except subprocess.TimeoutExpired:
                        print("CI Bambu variant:", label, "timeout")
                        continue
                    print("CI Bambu variant:", label, "exit", attempt.returncode,
                          "output_bytes", len(attempt.stdout),
                          "error_bytes", len(attempt.stderr))
                    print("CI Bambu stderr bounded:", repr(attempt.stderr[:200]))
                    if label == "tagged_machine_process_export" and attempt.returncode == 0:
                        import zipfile as _zipfile
                        archive_path = workdir / "tagged-sliced.3mf"
                        with _zipfile.ZipFile(archive_path) as archive:
                            gcode_members = [n for n in archive.namelist()
                                             if n.lower().endswith(".gcode")]
                            print("CI Bambu tagged export native G-code members:",
                                  gcode_members[:5])
                            if len(gcode_members) == 1:
                                exported = archive.read(gcode_members[0])
                                verify_multi_material_output(exported, {0, 1})
                                print("CI Bambu tagged export model regions:",
                                      verify_two_object_tool_regions(exported))
                    print("CI Bambu stdout bounded:", repr(attempt.stdout[:400]))
                    directory = workdir / label.replace("_", "-")
                    emitted = ([f for f in directory.rglob("*.gcode") if f.is_file()]
                               if directory.is_dir() else [])
                    print("CI Bambu variant G-code files:",
                          len(emitted), "bytes",
                          sum(f.stat().st_size for f in emitted[:4]))
                    if (label in ("no_overrides", "machine_process_only",
                                 "filament0_one_only", "filament0_blank_second",
                                 "tagged_no_overrides", "tagged_machine_process_only",
                                 "tagged_filaments_only",
                                 "tagged_machine_process_one_filament")
                            and len(emitted) == 1 and
                            0 < emitted[0].stat().st_size <= 16 * 1024 * 1024):
                        native_gcode = emitted[0].read_bytes()
                        import re
                        lines = native_gcode.decode("utf-8", "replace").splitlines()
                        exact_tools = {}
                        for code in lines:
                            match = re.fullmatch(r"T([0-9]{1,2})\s*", code.split(";", 1)[0].strip(), re.I)
                            if match:
                                exact_tools[match.group(1)] = exact_tools.get(match.group(1), 0) + 1
                        print("CI Bambu variant exact T commands:", label, exact_tools)
                        print("CI Bambu variant material mentions:", label,
                              sum("CHANGE_FILAMENT" in line.upper() for line in lines),
                              sum("FILAMENT_CHANGE" in line.upper() for line in lines))
                        print("CI Bambu variant gcode sample:", label,
                              [line[:140] for line in lines if line.lstrip().startswith("T")][:8])
                        try:
                            verify_multi_material_output(native_gcode, {0, 1})
                            if not painted:
                                coverage = verify_two_object_tool_regions(native_gcode)
                                print("CI Bambu variant two-cube deposition:",
                                      label, coverage)
                            else:
                                print("CI Bambu variant painted tools:", label, "passed")
                        except WorkerError as audit_error:
                            print("CI Bambu variant deposition audit:", label,
                                  "failed", str(audit_error)[:160])
                    for channel in (attempt.stdout, attempt.stderr):
                        for line in channel.decode("utf-8", "replace").splitlines()[-12:]:
                            if any(token in line.lower() for token in (
                                "error", "failed", "invalid", "warn", "filament",
                                "3mf", "plate", "slice", "unsupported")):
                                print("CI native diagnosis:", line[:240])
            raise
        gcode = (workdir / "output.gcode").read_bytes()
        verify_multi_material_output(gcode, {0, 1})
        coverage = (verify_painted_cube_tool_regions(gcode) if painted
                    else verify_two_object_tool_regions(gcode))
        # Evidence only: this fixed-geometry parser is shared with the K2
        # acceptance but makes no assertion about Bambu purge semantics.
        # The actual topology and tool-commands remain engine-specific.
        try:
            switch_evidence = summarize_k2_fixture_changeovers(gcode)
        except WorkerError as exc:
            switch_evidence = {"diagnostic": str(exc)[:160]}
        print("CI Bambu fixed model changeover/purge evidence:",
              json.dumps(switch_evidence, sort_keys=True))
        print("CI Bambu pinned G-code purge/tower markers:",
              [line[:100] for line in gcode.decode("utf-8", "replace").splitlines()
               if ("flush" in line.lower() or "prime tower" in line.lower()
                   or "wipe tower" in line.lower())][:12])
        from slicer_worker.material_gcode_audit import summarize_bambu_flush_signal
        flush_evidence = summarize_bambu_flush_signal(gcode)
        # Read generated G-code header, NOT the input process JSON. These
        # native values prove the slicer resolved directional purge volumes.
        native_header = {}
        for line in gcode.decode("utf-8", "replace").splitlines()[:2500]:
            for key in ("flush_volumes_matrix", "flush_multiplier",
                        "wipe_tower_x", "wipe_tower_y"):
                prefix = "; " + key + " = "
                if line.startswith(prefix):
                    native_header[key] = line[len(prefix):][:256].strip()
        flush_evidence["native_header"] = native_header
        print("CI Bambu native flush evidence:",
              json.dumps(flush_evidence, sort_keys=True))
        if variable_layers:
            code_lines = gcode.decode("utf-8", "replace").splitlines()
            print("CI Bambu layer-related native comments:",
                  [line[:150] for line in code_lines
                   if line.lstrip().startswith(";") and
                   ("layer" in line.lower() or "z:" in line.lower())][:30])
            print("CI Bambu early Z-motion samples:",
                  [line[:140] for line in code_lines
                   if line.startswith(("G0 ", "G1 ", "G00 ", "G01 "))
                   and " Z" in line.upper()][:30])
            layer_marks = []
            for line in gcode.decode("utf-8", "replace").splitlines():
                if line.startswith(";Z:") and len(line) < 40:
                    try:
                        layer_marks.append(float(line[3:].strip()))
                    except ValueError:
                        pass
            increments = [(z1, round(z1-z0, 3))
                          for z0, z1 in zip(layer_marks, layer_marks[1:])
                          if z1 > z0]
            bands = {
                "lower_0_10": [delta for z, delta in increments
                               if 2 <= z <= 8],
                "upper_0_30": [delta for z, delta in increments
                               if 12 <= z <= 18],
            }
            print("CI Bambu native variable-layer Z evidence:",
                  json.dumps({"marker_count": len(layer_marks),
                              "samples": layer_marks[:6],
                              "bands": {k: v[:12] for k, v in bands.items()},
                              "modal_counts": {
                                  k: {str(inc): vals.count(inc)
                                      for inc in sorted(set(vals))}
                                  for k, vals in bands.items()}}, sort_keys=True))
            from slicer_worker.material_gcode_audit import verify_bambu_fixture_variable_layers
            proof = verify_bambu_fixture_variable_layers(gcode)
            print("CI Bambu verified true layer increments:", json.dumps(proof, sort_keys=True))


        return {
            "status": "passed", "engine": "bambustudio",
            "fixture": "painted-facets" if painted else "two-objects",
            "gcode_bytes": receipt["bytes"],
            "gcode_sha256": hashlib.sha256(gcode).hexdigest(),
            "both_tools_extrude": True,
            "flush_multiplier": flush_multiplier,
            "tower_xy": tower_xy,
            "flush_evidence": flush_evidence,
            "variable_layers_requested": variable_layers,
            "detail_paint": detail_paint,
            **coverage,
        }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--binary", required=True)
    parser.add_argument("--profiles", required=True)
    parser.add_argument("--painted", action="store_true")
    parser.add_argument("--variable-layers", action="store_true")
    parser.add_argument("--detail-paint", choices=("support", "seam", "fuzzy", "combined"))
    parser.add_argument("--flush-multiplier", type=float, choices=(1.0, 2.0))
    parser.add_argument("--tower-x", type=float)
    parser.add_argument("--tower-y", type=float)
    parser.add_argument("--timeout", type=int, default=180)
    args = parser.parse_args()
    try:
        print(json.dumps(run_fixture(
            args.binary, args.profiles, painted=args.painted, timeout=args.timeout,
            flush_multiplier=args.flush_multiplier,
            variable_layers=args.variable_layers,
            detail_paint=args.detail_paint,
            tower_xy=((args.tower_x, args.tower_y)
                      if args.tower_x is not None and args.tower_y is not None
                      else None)),
            sort_keys=True))
    except (WorkerError, OSError, ValueError, KeyError, zipfile.BadZipFile) as exc:
        print(json.dumps({"status": "failed", "reason": str(exc)}))
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
