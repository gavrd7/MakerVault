"""Restricted slicing *worker-side* execution adapter.

This module is not imported by the MakerVault web or Celery processes.
It runs only inside a separately sandboxed, resource-limited worker image.
Callers provide a worker-controlled scratch directory containing fixed,
already validated input files; user data never becomes command line flags.
"""
from pathlib import Path
import os
import signal
import subprocess


MAX_GCODE_BYTES = 64 * 1024 * 1024
MAX_MODEL_BYTES = 32 * 1024 * 1024
MAX_PROFILE_BYTES = 2 * 1024 * 1024
MAX_LOG_BYTES = 4096
DEFAULT_TIMEOUT_SECONDS = 300


class WorkerError(ValueError):
    pass


def _regular_file(workdir: Path, name: str, maximum: int) -> Path:
    candidate = workdir / name
    if candidate.is_symlink() or not candidate.is_file():
        raise WorkerError("Required worker input is missing or unsafe.")
    if candidate.stat().st_size < 1 or candidate.stat().st_size > maximum:
        raise WorkerError("Worker input exceeds its size limit or is empty.")
    if candidate.resolve().parent != workdir.resolve():
        raise WorkerError("Worker input must remain in isolated scratch.")
    return candidate


def _output_path(workdir: Path) -> Path:
    candidate = workdir / "output.gcode"
    if candidate.exists() or candidate.is_symlink():
        raise WorkerError("Output already exists; fresh scratch is required.")
    return candidate


def prusa_command(binary: Path, workdir: Path) -> list[str]:
    """The verified worker image provides the executable, never a browser."""
    if binary.is_symlink() or not binary.is_file() or not os.access(binary, os.X_OK):
        raise WorkerError("Pinned PrusaSlicer executable is unavailable.")
    model = _regular_file(workdir, "input.stl", MAX_MODEL_BYTES)
    profiles = [
        _regular_file(workdir, name, MAX_PROFILE_BYTES)
        for name in ("printer.ini", "filament.ini", "process.ini")
    ]
    for profile in profiles:
        # Native profiles can include arbitrary post-processing scripts.
        # Reject execution hooks before launching any slicer.
        data = profile.read_bytes()
        if b"\\x00" in data:
            raise WorkerError("Native profile contains binary data.")
        for line in data.decode("utf-8", "replace").splitlines():
            key = line.partition("=")[0].strip().lower()
            if key in {"post_process", "post_process_scripts"}:
                raise WorkerError("Post-processing scripts are forbidden.")
    output = _output_path(workdir)
    return [
        str(binary), "--load", str(profiles[0]), "--load", str(profiles[1]),
        "--load", str(profiles[2]), "--export-gcode", "--output", str(output),
        str(model),
    ]


def run_prusa(
    binary: Path, workdir: Path, *, timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS
) -> dict:
    """Run exactly one already-approved Prusa job within the worker sandbox.

    This is not a sandbox implementation: the CONTAINER must independently
    constrain filesystem, network, credentials, CPU, memory, PIDs and storage.
    """
    if not isinstance(timeout_seconds, int) or not 1 <= timeout_seconds <= 900:
        raise WorkerError("Invalid slice timeout.")
    workdir = Path(workdir).resolve(strict=True)
    if not workdir.is_dir():
        raise WorkerError("Worker scratch directory is invalid.")
    command = prusa_command(Path(binary), workdir)
    proc = None
    try:
        proc = subprocess.Popen(
            command, cwd=str(workdir), env={
                "HOME": str(workdir), "TMPDIR": str(workdir), "LANG": "C.UTF-8",
                "LC_ALL": "C.UTF-8", "PATH": "/usr/bin:/bin",
            }, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True,
        )
        try:
            proc.communicate(timeout=timeout_seconds)
        except subprocess.TimeoutExpired:
            os.killpg(proc.pid, signal.SIGKILL)
            proc.communicate()
            raise WorkerError("Slicing timed out.") from None
        if proc.returncode != 0:
            # Never expose raw engine logs: profiles may contain secrets or
            # cloud endpoints. Dedicated scrubbed diagnostics come later.
            raise WorkerError("Slicing engine failed. Check the selected native presets.")
        output = _regular_file(workdir, "output.gcode", MAX_GCODE_BYTES)
        with output.open("rb") as stream:
            head = stream.read(min(4096, output.stat().st_size))
        if b"\x00" in head:
            raise WorkerError("Output is not plain-text G-code.")
        return {"status": "completed", "gcode_path": str(output), "bytes": output.stat().st_size}
    except OSError as exc:
        raise WorkerError("Worker could not launch the installed slicing engine.") from exc
