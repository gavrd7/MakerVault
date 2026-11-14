"""OrcaSlicer acceptance-fixture verifier for a real, pinned isolated engine.

Usage INSIDE the reviewed worker container:
  python3 -m slicer_worker.verify_orca --binary /path/to/orca-slicer \
      --model /fixtures/benchy.stl --printer /fixtures/printer.json \
      --filament /fixtures/filament.json --process /fixtures/process.json

This tool does not install an engine, accept network URLs, or mark a worker
verified. It fails unless the real CLI emits bounded, compatible G-code.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory

from .orca_runner import run_orca
from .runner import MAX_MODEL_BYTES, MAX_PROFILE_BYTES, WorkerError


def verify_fixture(binary: Path, model: Path, printer: Path, filament: Path, process: Path, engine_version: str = ""):
    binary = Path(binary)
    if not isinstance(engine_version, str) or len(engine_version) > 80:
        raise WorkerError("Invalid exact engine version.")
    if binary.is_symlink() or not binary.is_file() or not 0 < binary.stat().st_size <= 1024 * 1024 * 1024:
        raise WorkerError("The fixture must use an existing reviewed Orca executable.")
    engine_sha = hashlib.sha256()
    with binary.open("rb") as binary_file:
        while block := binary_file.read(1024 * 1024):
            engine_sha.update(block)
    with TemporaryDirectory(prefix="makervault-orca-fixture-") as temp:
        root = Path(temp)
        for source, name, size in (
            (model, "input.stl", MAX_MODEL_BYTES),
            (printer, "printer.json", MAX_PROFILE_BYTES),
            (filament, "filament.json", MAX_PROFILE_BYTES),
            (process, "process.json", MAX_PROFILE_BYTES),
        ):
            source = Path(source)
            if source.is_symlink() or not source.is_file() or not 0 < source.stat().st_size <= size:
                raise WorkerError("Fixture input is missing, a symlink or oversized.")
            with source.open("rb") as inp, (root / name).open("xb") as out:
                data = inp.read(size + 1)
                if not 0 < len(data) <= size:
                    raise WorkerError("Fixture data exceeds size limit.")
                out.write(data)
        result = run_orca(binary, root)
        data = Path(result["gcode_path"]).read_bytes()
        if not data or b"\x00" in data or not any(
            command in data.upper() for command in (b"G0 ", b"G1 ", b"G00 ", b"G01 ")
        ):
            raise WorkerError("The real engine produced no valid plain-text toolpath.")
        for forbidden in (b"M112", b"M500", b"M501", b"M502", b"M997"):
            for line in data.upper().splitlines():
                if line.lstrip().startswith(forbidden):
                    raise WorkerError("Unsafe firmware-control command in fixture output.")
        return {
            "engine": "orcaslicer",
            "engine_version": engine_version,
            "engine_binary_sha256": engine_sha.hexdigest(),
            "fixture_sha256": hashlib.sha256((root / "input.stl").read_bytes()).hexdigest(),
            "printer_profile_sha256": hashlib.sha256((root / "printer.json").read_bytes()).hexdigest(),
            "filament_profile_sha256": hashlib.sha256((root / "filament.json").read_bytes()).hexdigest(),
            "process_profile_sha256": hashlib.sha256((root / "process.json").read_bytes()).hexdigest(),
            "gcode_sha256": hashlib.sha256(data).hexdigest(),
            "gcode_bytes": len(data),
            "cli_invocation": "verified",
            "approved_for_production": False,
        }


def main():
    parser = argparse.ArgumentParser(description="Validate one real OrcaSlicer CLI fixture")
    for name in ("binary", "model", "printer", "filament", "process"):
        parser.add_argument("--" + name, required=True, type=Path)
    parser.add_argument("--engine-version", required=True, type=str,
                        help="Exact release/build version independently checked by administrator")
    args = parser.parse_args()
    try:
        result = verify_fixture(args.binary, args.model, args.printer, args.filament, args.process, args.engine_version)
    except WorkerError as exc:
        parser.exit(1, "Orca fixture verification failed: " + str(exc) + "\n")
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
