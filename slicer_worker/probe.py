"""Run an offline, real-binary slicer acceptance fixture before deployment.

This command NEVER enables a slicer or writes MakerVault application records.
Run inside a disposable, isolated build/test container with an approved engine
binary and matching resolved native profiles. No printer connection is needed.

Example:
 python3 -m slicer_worker.probe --engine orcaslicer --version 2.4.2 \
   --binary /opt/engines/orcaslicer --printer /fixtures/printer.json \
   --filament /fixtures/filament.json --process /fixtures/process.json
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import struct
import sys
import tempfile
import io
import zipfile
from xml.etree import ElementTree as ET

from .runner import MAX_PROFILE_BYTES, MAX_GCODE_BYTES, WorkerError
from .orca_runner import run_orca
from .creality_runner import run_creality
from .three_mf_validation import validate_worker_3mf
from .material_gcode_audit import verify_multi_material_output, expected_native_tools, verify_two_object_tool_regions, verify_k2_fixture_purge_tower_evidence
from .k2_cfs_acceptance import k2_offline_profile_evidence

ENGINES = {"orcaslicer": run_orca, "crealityprint": run_creality}
GCODE_EXTRUSION = re.compile(
    rb"(?m)^\s*G0?1\s+[^\r\n]*\bE[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:\s|$)", re.I
)


def fixture_stl():
    """Minimal non-planar binary tetrahedron with four triangle facets."""
    points = (
        ((0, 0, 0), (10, 0, 0), (0, 10, 0)),
        ((0, 0, 0), (0, 0, 10), (10, 0, 0)),
        ((0, 0, 0), (0, 10, 0), (0, 0, 10)),
        ((10, 0, 0), (0, 0, 10), (0, 10, 0)),
    )
    header = b"MakerVault offline binary acceptance fixture".ljust(80, b" ")
    triangles = b"".join(
        struct.pack("<12fH", 0, 0, 1, *a, *b, *c, 0)
        for a, b, c in points
    )
    return header + struct.pack("<I", len(points)) + triangles


def _read_source(path, limit):
    source = Path(path)
    if source.is_symlink() or not source.is_file():
        raise WorkerError("A fixture source is missing or is a symbolic link.")
    with source.open("rb") as stream:
        data = stream.read(limit + 1)
    if not data or len(data) > limit:
        raise WorkerError("Fixture source file is missing or exceeds its limit.")
    return data


def _fingerprint(path):
    file = Path(path)
    if not file.is_absolute() or file.is_symlink() or not file.is_file() or not os.access(file, os.X_OK):
        raise WorkerError("Select an executable, absolute, non-symlinked binary path.")
    digest = hashlib.sha256()
    with file.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _validate_gcode(path, *, min_extrusion_span_x=None):
    file = Path(path)
    if file.is_symlink() or not file.is_file() or not 0 < file.stat().st_size <= MAX_GCODE_BYTES:
        raise WorkerError("The engine did not return a valid, bounded G-code file.")
    with file.open("rb") as stream:
        data = stream.read(MAX_GCODE_BYTES + 1)
    if len(data) > MAX_GCODE_BYTES or b"\x00" in data[:4096]:
        raise WorkerError("The engine produced invalid or binary G-code.")
    if not GCODE_EXTRUSION.search(data):
        raise WorkerError("The engine produced no extrusion movement; fixture rejected.")
    if min_extrusion_span_x is not None:
        # This is limited to the fixed two-object CI fixture. It verifies
        # extruding toolpaths exist at both separated X locations rather than
        # accepting G-code for a single object on the plate.
        x_positions = []
        for line in data.splitlines():
            code = line.partition(b";")[0].strip().upper()
            if not GCODE_EXTRUSION.match(code):
                continue
            x = re.search(rb"(?:^|\s)X([-+]?(?:\d+(?:\.\d*)?|\.\d+))(?=\s|$)", code)
            if x:
                x_positions.append(float(x.group(1)))
        span = max(x_positions) - min(x_positions) if x_positions else 0
        if len(x_positions) < 2 or span < min_extrusion_span_x:
            raise WorkerError(
                "Two-object fixture extrusion coverage insufficient: "
                f"X-extrusion moves={len(x_positions)}, X-span={span:.2f} mm; "
                f"required >= {min_extrusion_span_x} mm."
            )
    return {"gcode_sha256": hashlib.sha256(data).hexdigest(), "gcode_bytes": len(data)}


def _verify_two_native_object_effects(path, *, reverse=False):
    """Check toolpaths reflect different process settings on equal 20mm cubes.

    The fixture deliberately uses 15%/2-wall left and 37%/5-wall right.
    Count positive extrusion only in each cube's bounded XY region. Global
    G-code comments are not evidence of effective per-object settings.
    """
    gcode = Path(path).read_bytes()
    last_x = last_y = 0.0
    last_e = 0.0
    relative_extrusion = False
    totals = [0.0, 0.0]
    moves = [0, 0]
    value_pattern = re.compile(rb"(?:^|\s)([XYE])([-+]?(?:\d+(?:\.\d*)?|\.\d+))(?=\s|$)", re.I)
    for raw in gcode.splitlines():
        code = raw.partition(b";")[0].strip().upper()
        if code == b"M82":
            relative_extrusion = False
            continue
        if code == b"M83":
            relative_extrusion = True
            continue
        if code.startswith(b"G92"):
            params = {key: float(value) for key, value in value_pattern.findall(code)}
            if b"E" in params:
                last_e = params[b"E"]
            continue
        if not (code.startswith(b"G1 ") or code.startswith(b"G01 ")):
            # Track travel X/Y without treating it as extrusion.
            if code.startswith(b"G0 ") or code.startswith(b"G00 "):
                params = {key: float(value) for key, value in value_pattern.findall(code)}
                last_x, last_y = params.get(b"X", last_x), params.get(b"Y", last_y)
            continue
        params = {key: float(value) for key, value in value_pattern.findall(code)}
        x, y = params.get(b"X", last_x), params.get(b"Y", last_y)
        extruded = 0.0
        if b"E" in params:
            extruded = (params[b"E"] if relative_extrusion
                        else params[b"E"] - last_e)
            last_e = params[b"E"] if not relative_extrusion else last_e
        last_x, last_y = x, y
        if extruded <= 0 or not (b"X" in params or b"Y" in params):
            continue
        region = (0 if 64 <= x <= 86 and 99 <= y <= 121 else
                  1 if 134 <= x <= 156 and 99 <= y <= 121 else None)
        if region is not None:
            totals[region] += extruded
            moves[region] += 1
    if min(moves) < 20 or min(totals) <= 0:
        raise WorkerError(
            "Per-object G-code verification is missing extrusion in one fixture region."
        )
    ratio = totals[1] / totals[0]
    # Compare both the original and reversed setting assignments. A position-
    # dependent difference cannot satisfy both experiments: the high-infill,
    # five-wall object must consume more filament wherever it is placed.
    if (ratio >= 0.8 if reverse else ratio <= 1.2):
        raise WorkerError(
            f"Native object overrides were not proven effective: "
            f"left={totals[0]:.2f} mm, right={totals[1]:.2f} mm, ratio={ratio:.2f}; "
            f"reversed={reverse}."
        )
    return {"left_extrusion_mm": round(totals[0], 3),
            "right_extrusion_mm": round(totals[1], 3),
            "effective_extrusion_ratio": round(ratio, 3),
            "left_moves": moves[0], "right_moves": moves[1]}


def run_probe(*, engine, version, binary, printer, filament, process, timeout=120, model=None, expected_objects=1, expected_islands=1, experimental_all_plates=False, experimental_no_arrange=False, verify_object_effects=False, reverse_object_effects=False, second_filament=None, audit_changeovers=False):
    """Run the *real* worker adapter with the *real* binary and report evidence.

    No mock success, no automatic deployment and no stored G-code artifact.
    """
    if engine not in ENGINES:
        raise WorkerError("Only OrcaSlicer and Creality Print are supported by this probe.")
    if not isinstance(version, str) or not 1 <= len(version) <= 80:
        raise WorkerError("A pinned engine version is required.")
    if not isinstance(timeout, int) or not 1 <= timeout <= 900:
        raise WorkerError("Probe timeout must be between 1 and 900 seconds.")
    if (expected_objects not in (1, 2) or expected_islands not in (1, 2)
            or ((expected_objects == 2 or expected_islands == 2) and not model)
            or (expected_objects == 2 and expected_islands == 2)):
        raise WorkerError("Explicit two-object 3MF input is required for multi-model acceptance.")
    if reverse_object_effects and not verify_object_effects:
        raise WorkerError("Reversed object settings require G-code effect verification.")
    if audit_changeovers and second_filament is None:
        raise WorkerError("K2 changeover audit requires a two-tool fixture.")
    if second_filament is not None and (engine != "orcaslicer" or not model or
            expected_objects != 2 or expected_islands != 1 or verify_object_effects):
        raise WorkerError("Two-tool native acceptance requires a two-object Orca 3MF.")
    model_bytes = None
    if model is not None:
        if (expected_objects != 2 and expected_islands != 2) or Path(model).suffix.lower() != ".3mf":
            raise WorkerError("Only the two-object core 3MF acceptance fixture is supported.")
        model_bytes = _read_source(model, 32 * 1024 * 1024)
        validate_worker_3mf(model_bytes, native_tool_count=2 if second_filament is not None else None)
        with zipfile.ZipFile(io.BytesIO(model_bytes)) as package:
            xml = ET.fromstring(package.read("3D/3dmodel.model"))
        namespace = "{http://schemas.microsoft.com/3dmanufacturing/core/2015/02}"
        count = len(xml.findall("./" + namespace + "build/" + namespace + "item"))
        if count != expected_objects:
            raise WorkerError("The reference 3MF does not contain the expected build instance count.")
    binary_sha256 = _fingerprint(binary)
    inputs = {
        "printer.json": _read_source(printer, MAX_PROFILE_BYTES),
        "filament.json": _read_source(filament, MAX_PROFILE_BYTES),
        "process.json": _read_source(process, MAX_PROFILE_BYTES),
    }
    k2_profile = (k2_offline_profile_evidence(inputs["printer.json"], inputs["process.json"])
                  if audit_changeovers else None)
    if second_filament is not None:
        inputs["filament-0.json"] = inputs["filament.json"]
        inputs["filament-1.json"] = _read_source(second_filament, MAX_PROFILE_BYTES)
    with tempfile.TemporaryDirectory(prefix="makervault-engine-probe-") as tmp:
        root = Path(tmp)
        (root / ("input.3mf" if model_bytes is not None else "input.stl")).write_bytes(
            model_bytes if model_bytes is not None else fixture_stl())
        for name, data in inputs.items():
            (root / name).write_bytes(data)
        if (experimental_all_plates or experimental_no_arrange) and (engine != "orcaslicer" or model is None):
            raise WorkerError("Experimental plate mode requires Orca 3MF input.")
        options = ({"experimental_all_plates": experimental_all_plates,
                    "experimental_no_arrange": experimental_no_arrange}
                   if engine == "orcaslicer" else {})
        receipt = ENGINES[engine](Path(binary), root, timeout_seconds=timeout, **options)
        if receipt.get("status") != "completed":
            raise WorkerError("The engine did not complete the slicing fixture.")
        output = _validate_gcode(root / "output.gcode",
                                 min_extrusion_span_x=35 if expected_objects == 2 or expected_islands == 2 else None)
        if second_filament is not None:
            generated = (root / "output.gcode").read_bytes()
            verify_multi_material_output(generated, expected_native_tools(model_bytes))
            output.update(verify_two_object_tool_regions(generated))
            output["native_multi_tool_verified"] = True
            if audit_changeovers:
                output["k2_changeover_evidence"] = verify_k2_fixture_purge_tower_evidence(generated)
        if verify_object_effects:
            if expected_objects != 2 or model is None or engine != "orcaslicer":
                raise WorkerError("Per-object effect probe requires independent Orca 3MF.")
            output.update(_verify_two_native_object_effects(
                root / "output.gcode", reverse=reverse_object_effects))
    return {
        "status": "passed",
        "engine": engine, "engine_version": version,
        "binary_sha256": binary_sha256,
        "fixture": "makervault-two-object-3mf-v1" if model_bytes is not None
                   else "makervault-tetrahedron-binary-v1",
        "object_count": expected_objects,
        "expected_geometry_islands": expected_islands,
        "profile_sha256": {key.removesuffix(".json"): hashlib.sha256(data).hexdigest()
                           for key, data in inputs.items()},
        **output,
        **({"k2_profile_evidence": k2_profile} if k2_profile is not None else {}),
        "note": "Evidence only; no engine was installed, approved or enabled in MakerVault.",
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--engine", required=True, choices=sorted(ENGINES))
    parser.add_argument("--version", required=True)
    parser.add_argument("--binary", required=True)
    parser.add_argument("--printer", required=True)
    parser.add_argument("--filament", required=True)
    parser.add_argument("--process", required=True)
    parser.add_argument("--timeout", type=int, default=120)
    parser.add_argument("--model", help="Optional real two-model MakerVault core 3MF fixture")
    parser.add_argument("--second-filament", help="Second ordered native filament preset (offline only)")
    parser.add_argument("--audit-changeovers", action="store_true",
                        help="Report bounded K2 two-cube toolchange/purge-region evidence")
    parser.add_argument("--expected-objects", type=int, choices=(1, 2), default=1)
    parser.add_argument("--expected-islands", type=int, choices=(1, 2), default=1)
    parser.add_argument("--experimental-all-plates", action="store_true")
    parser.add_argument("--experimental-no-arrange", action="store_true")
    parser.add_argument("--verify-object-effects", action="store_true")
    parser.add_argument("--reverse-object-effects", action="store_true")
    args = parser.parse_args(argv)
    try:
        print(json.dumps(run_probe(**vars(args)), indent=2, sort_keys=True))
    except (WorkerError, OSError, ValueError) as exc:
        print(json.dumps({"status": "failed", "reason": str(exc)}), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
