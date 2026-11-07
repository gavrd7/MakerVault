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

from .runner import MAX_PROFILE_BYTES, MAX_GCODE_BYTES, WorkerError
from .orca_runner import run_orca
from .creality_runner import run_creality

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


def _validate_gcode(path):
    file = Path(path)
    if file.is_symlink() or not file.is_file() or not 0 < file.stat().st_size <= MAX_GCODE_BYTES:
        raise WorkerError("The engine did not return a valid, bounded G-code file.")
    with file.open("rb") as stream:
        data = stream.read(MAX_GCODE_BYTES + 1)
    if len(data) > MAX_GCODE_BYTES or b"\x00" in data[:4096]:
        raise WorkerError("The engine produced invalid or binary G-code.")
    if not GCODE_EXTRUSION.search(data):
        raise WorkerError("The engine produced no extrusion movement; fixture rejected.")
    return {"gcode_sha256": hashlib.sha256(data).hexdigest(), "gcode_bytes": len(data)}


def run_probe(*, engine, version, binary, printer, filament, process, timeout=120):
    """Run the *real* worker adapter with the *real* binary and report evidence.

    No mock success, no automatic deployment and no stored G-code artifact.
    """
    if engine not in ENGINES:
        raise WorkerError("Only OrcaSlicer and Creality Print are supported by this probe.")
    if not isinstance(version, str) or not 1 <= len(version) <= 80:
        raise WorkerError("A pinned engine version is required.")
    if not isinstance(timeout, int) or not 1 <= timeout <= 900:
        raise WorkerError("Probe timeout must be between 1 and 900 seconds.")
    binary_sha256 = _fingerprint(binary)
    inputs = {
        "printer.json": _read_source(printer, MAX_PROFILE_BYTES),
        "filament.json": _read_source(filament, MAX_PROFILE_BYTES),
        "process.json": _read_source(process, MAX_PROFILE_BYTES),
    }
    with tempfile.TemporaryDirectory(prefix="makervault-engine-probe-") as tmp:
        root = Path(tmp)
        (root / "input.stl").write_bytes(fixture_stl())
        for name, data in inputs.items():
            (root / name).write_bytes(data)
        receipt = ENGINES[engine](Path(binary), root, timeout_seconds=timeout)
        if receipt.get("status") != "completed":
            raise WorkerError("The engine did not complete the slicing fixture.")
        output = _validate_gcode(root / "output.gcode")
    return {
        "status": "passed",
        "engine": engine, "engine_version": version,
        "binary_sha256": binary_sha256,
        "fixture": "makervault-tetrahedron-binary-v1",
        "profile_sha256": {key.removesuffix(".json"): hashlib.sha256(data).hexdigest()
                           for key, data in inputs.items()},
        **output,
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
    args = parser.parse_args(argv)
    try:
        print(json.dumps(run_probe(**vars(args)), indent=2, sort_keys=True))
    except (WorkerError, OSError, ValueError) as exc:
        print(json.dumps({"status": "failed", "reason": str(exc)}), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
