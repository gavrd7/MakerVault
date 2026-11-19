"""Offline Creality 7.3.x native-project diagnostic matrix.

Run ONLY inside the existing isolated slicer-worker container. No network,
printer endpoints, uploaded firmware or user-supplied CLI flags are invoked.
Requires an existing candidate project 3MF (and optionally a known-good 3MF).
No G-code is copied outside scratch. The JSON report is safe to share.
"""
import argparse
import copy
import hashlib
import io
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import time
import zipfile

from .creality_runner import _cli_validation_category, _cli_failure_reason
from .creality_project_validation import validate_creality_project
from .engine_registry import configured_engines
from .runner import WorkerError
from .headless_env import slicing_environment
from .creality_single_control import single_material_control
from .creality_reference_diagnostics import compare_projects, compare_to_bundled_reference

MAX_PROJECT = 32 * 1024 * 1024
MAX_CAPTURE = 256 * 1024
MAX_SECONDS = 180
SETTINGS = "Metadata/project_settings.config"
GCODE_SUFFIX = ".gcode"


def _read_project(path):
    p = Path(path)
    if p.is_symlink() or not p.is_file() or not 0 < p.stat().st_size <= MAX_PROJECT:
        raise ValueError("Project input must be one regular, bounded 3MF file.")
    data = p.read_bytes()
    # Preserve strict existing worker validation for MakerVault test projects.
    validate_creality_project(data, native_tool_count=2)
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        config = json.loads(z.read(SETTINGS))
    return data, config


def _repack(original, settings):
    encoded = json.dumps(settings, separators=(",", ":"), ensure_ascii=False).encode()
    if len(encoded) > 4 * 1024 * 1024:
        raise ValueError("Oversized test configuration.")
    output = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(original)) as src:
        with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as dest:
            for name in src.namelist():
                dest.writestr(name, encoded if name == SETTINGS else src.read(name))
    data = output.getvalue()
    if len(data) > MAX_PROJECT:
        raise ValueError("Oversized test project.")
    validate_creality_project(data, native_tool_count=2)
    return data


def _cases(config):
    """A small, deterministic isolation matrix; not guesses at arbitrary CLI flags."""
    cases = [("baseline", None, "Original MakerVault generated native 3MF")]
    # When Creality reports filament validation, first isolate the physical
    # one-nozzle map, then safe tower and vector serialization changes.
    cases.append(("no-explicit-filament-map",
                  {"filament_map": None},
                  "Let Creality derive its native filament/nozzle mapping"))
    cases.append(("explicit-single-nozzle",
                  {"filament_map": ["1"] * len(config.get("filament_settings_id", []))},
                  "Assign both logical filaments to physical nozzle one"))
    cases.append(("tower-disabled",
                  {"enable_prime_tower": "0"},
                  "Disable tower for diagnosis only (not an approved print)"))
    vectors = {}
    for key, value in config.items():
        if (key.startswith("filament_") or key in {
                "nozzle_temperature", "nozzle_temperature_initial_layer",
                "cool_plate_temp", "hot_plate_temp", "textured_plate_temp",
                "fan_min_speed", "fan_max_speed"}) and isinstance(value, list):
            # Avoid mutating vector shape; report unusual values separately.
            if len(value) == len(config.get("filament_settings_id", [])) and all(type(v) in (str, int, float, bool) for v in value):
                vectors[key] = [str(int(v)) if isinstance(v, bool) else str(v) for v in value]
    cases.append(("normalised-filament-scalars", vectors,
                  "Normalise existing native per-material vector element types"))
    # Keep both object-to-tool assignments, but eliminate differences between
    # material parameters. If only this case passes, the issue is likely in
    # the distinct native filament values rather than mapping/geometry.
    identical = {}
    for key, value in config.items():
        if (key.startswith("filament_") or key in {
                "nozzle_temperature", "nozzle_temperature_initial_layer",
                "cool_plate_temp", "hot_plate_temp", "textured_plate_temp",
                "fan_min_speed", "fan_max_speed"
            }) and isinstance(value, list) and len(value) == len(config.get("filament_settings_id", [])):
            if key not in {"filament_settings_id", "filament_map", "filament_ids"}:
                identical[key] = [value[0]] * len(value)
    cases.append(("identical-filament-parameters", identical,
                  "Keep both logical tools but give both the same native material values"))
    return cases


def _scrubbed_tail_category(raw):
    # Never write raw engine logs or parsed engine-provided user text.
    category = _cli_validation_category(raw)
    return category if category in {
        "prime-tower", "layer-height", "line-width", "nozzle",
        "flow", "filament", "supports", "build-plate",
    } else "unclassified"


def _known_validation_reason(raw):
    """Return only exact, public Creality validation reasons.

    These fixed strings originate in Creality Print's Print::validate and
    check_multi_filament_valid. No substrings of user profiles or raw logs
    are ever copied into the report.
    """
    text = raw.decode("utf-8", errors="replace").lower()
    known = (
        ("large difference of temperature together", "incompatible-material-temperature-ranges"),
        ("the mixed filament references a filament that no longer exists", "missing-mixed-filament-reference"),
        ("filaments of different types cannot be mixed", "mixed-filament-type-mismatch"),
        ("no extrusions under current settings", "no-active-extrusions"),
        ("prime tower on every layer", "prime-tower-layer-requirement"),
    )
    for phrase, reason in known:
        if phrase in text:
            return reason
    return None


def _engine_run(binary, project, timeout_seconds):
    with tempfile.TemporaryDirectory(prefix="creality-matrix-") as temp:
        root = Path(temp)
        model = root / "input.3mf"
        model.write_bytes(project)
        out = root / "output"
        command = [
            str(binary), "--cli", "--slice", "0", "--outputdir", str(out),
            "--need-gcode-file", str(model),
        ]
        start = time.monotonic()
        try:
            # Capture in a bounded scratch-backed file rather than an
            # unbounded PIPE: some native CLI failures log very heavily.
            with tempfile.TemporaryFile(mode="w+b") as diagnostic:
                result = subprocess.run(
                    command, cwd=root, env=slicing_environment(root),
                    stdout=diagnostic, stderr=subprocess.STDOUT,
                    timeout=timeout_seconds, check=False,
                )
                diagnostic.seek(0, os.SEEK_END)
                size = diagnostic.tell()
                diagnostic.seek(max(0, size - MAX_CAPTURE), os.SEEK_SET)
                output = diagnostic.read(MAX_CAPTURE)
                code = result.returncode
        except subprocess.TimeoutExpired:
            return {"status": "timeout", "duration_seconds": timeout_seconds}
        duration = round(time.monotonic() - start, 2)
        safe = {"status": "passed" if code == 0 else "failed",
                "exit_code": code, "duration_seconds": duration}
        if code == 205:
            safe.update({"native_error": "CLI_VALIDATE_ERROR (-51)",
                         "validation_category": _scrubbed_tail_category(output)})
            known_reason = _known_validation_reason(output)
            if known_reason:
                safe["known_validation_reason"] = known_reason
        elif code == 250:
            safe["native_error"] = "CLI_DATA_FILE_ERROR (-6)"
        elif code == 232:
            safe["native_error"] = "CLI_FILE_VERSION_NOT_SUPPORTED (-24)"
        elif code == 254:
            safe["native_error"] = "CLI_INVALID_PARAMS (-2)"
        elif code != 0:
            # An unknown code has no trustworthy classification.
            safe["native_error"] = "unclassified"
        if code == 0:
            gcode = list(out.glob("*" + GCODE_SUFFIX)) if out.is_dir() else []
            if len(gcode) != 1 or not gcode[0].is_file():
                safe.update(status="no-gcode")
            else:
                size = gcode[0].stat().st_size
                safe.update(gcode_bytes=size,
                            status="passed" if 40 < size <= 64 * 1024 * 1024
                            else "invalid-gcode")
                # No G-code is exported from scratch.
        return safe


def run_matrix(project_path, *, reference_path=None, timeout_seconds=120):
    if not 10 <= timeout_seconds <= MAX_SECONDS:
        raise ValueError("Diagnostic timeout must be between 10 and 180 seconds.")
    engines = configured_engines()
    engine = engines.get("crealityprint")
    if not engine or not engine["version"].startswith("7.3."):
        raise RuntimeError("A verified Creality Print 7.3.x worker engine is required.")
    project, config = _read_project(project_path)
    report = {
        "schema": 1, "engine": "crealityprint",
        "engine_version": engine["version"],
        "binary_sha256": engine["binary_sha256"],
        "candidate_sha256": hashlib.sha256(project).hexdigest(),
        "test_results": [], "reference": None,
        "warning": "Diagnosis only; no G-code is approved for printing.",
    }
    if reference_path is None:
        # Uses a sanitised schema derived from an uploaded genuine Creality
        # project. The actual private reference file is NEVER required here.
        report["reference"] = compare_to_bundled_reference(project)
    if reference_path is not None:
        # Never execute third-party reference 3MFs. Only inspect bounded
        # archive structure and public option key names/types.
        p = Path(reference_path)
        if p.is_symlink() or not p.is_file() or not 0 < p.stat().st_size <= MAX_PROJECT:
            raise ValueError("Reference 3MF must be a bounded regular file.")
        report["reference"] = compare_projects(project, p.read_bytes())
    # True single-material control reduces object count and active palette.
    try:
        single = single_material_control(project)
    except (ValueError, KeyError, TypeError, zipfile.BadZipFile) as exc:
        # A diagnostic control that cannot be constructed must not prevent
        # the original baseline and remaining five cases from executing.
        single_result = {"status": "control-construction-failed",
                         "error_type": type(exc).__name__}
        single_digest = None
    else:
        single_result = _engine_run(engine["binary"], single, timeout_seconds)
        single_digest = hashlib.sha256(single).hexdigest()
    report["test_results"].append({
        "case": "single-model-single-material",
        "description": "One original model, one native filament, tower disabled",
        "configuration_sha256": single_digest,
        **single_result,
    })
    for name, edits, description in _cases(config):
        variant = copy.deepcopy(config)
        if edits:
            for key, value in edits.items():
                if value is None:
                    variant.pop(key, None)
                else:
                    variant[key] = value
        blob = project if edits is None else _repack(project, variant)
        outcome = _engine_run(engine["binary"], blob, timeout_seconds)
        report["test_results"].append({
            "case": name, "description": description,
            "configuration_sha256": hashlib.sha256(blob).hexdigest(),
            **outcome,
        })
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", required=True,
                        help="Candidate MakerVault native Creality two-material project 3MF")
    parser.add_argument("--reference", help="Optional genuine Creality 7.3.1-exported 3MF")
    parser.add_argument("--timeout", type=int, default=120)
    parser.add_argument("--output", required=True, help="Safe JSON report path in scratch")
    args = parser.parse_args(argv)
    report = run_matrix(args.project, reference_path=args.reference,
                        timeout_seconds=args.timeout)
    target = Path(args.output)
    if target.exists() or target.is_symlink() or target.parent != Path("/tmp"):
        raise ValueError("Report must use a fresh path directly in /tmp.")
    target.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n",
                      encoding="utf-8")
    print("Creality diagnostic matrix completed; results: " + str(target))
    return 0 if any(row["status"] == "passed" for row in report["test_results"]) else 2


if __name__ == "__main__":
    raise SystemExit(main())
