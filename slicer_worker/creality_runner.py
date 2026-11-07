"""Creality Print CLI adapter for one explicitly approved binary.

Uses Creality's documented native --load_settings/--load_filaments flags,
not the similarly named OrcaSlicer flags. A real tested version and fixture
receipt are required before this engine may be marked verified/ready.
"""
import json
import os
from pathlib import Path
import signal
import subprocess

from .runner import (
    DEFAULT_TIMEOUT_SECONDS, MAX_GCODE_BYTES, MAX_MODEL_BYTES,
    MAX_PROFILE_BYTES, WorkerError, _regular_file, _output_path,
)
from .stl_validation import StlValidationError, validate_stl
from .three_mf_validation import validate_worker_3mf
from .headless_env import slicing_environment
from .orca_runner import FORBIDDEN_KEYS


def _check_native_json(path):
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (ValueError, OSError, UnicodeError):
        raise WorkerError("Invalid Creality Print JSON profile.") from None
    if not isinstance(value, dict) or value.get("inherits"):
        raise WorkerError("Creality Print profile requires a self-contained, verified native preset.")
    def walk(item, depth=0):
        if depth > 12:
            raise WorkerError("Creality Print profile nesting exceeds the limit.")
        if isinstance(item, dict):
            if len(item) > 4096:
                raise WorkerError("Creality Print profile has too many properties.")
            for key, child in item.items():
                if str(key).strip().lower() in FORBIDDEN_KEYS:
                    raise WorkerError("Unsafe native profile setting.")
                walk(child, depth + 1)
        elif isinstance(item, list):
            if len(item) > 4096:
                raise WorkerError("Creality Print profile contains too many entries.")
            for child in item:
                walk(child, depth + 1)
    walk(value)


def creality_command(binary: Path, workdir: Path):
    """Construct fixed arguments without accepting arbitrary client options."""
    if binary.is_symlink() or not binary.is_file() or not os.access(binary, os.X_OK):
        raise WorkerError("Verified Creality Print executable is unavailable.")
    is_project = (workdir / "input.3mf").exists()
    model = _regular_file(workdir, "input.3mf" if is_project else "input.stl", MAX_MODEL_BYTES)
    if is_project:
        validate_worker_3mf(model.read_bytes())
    else:
        try:
            validate_stl(model.read_bytes())
        except StlValidationError as exc:
            raise WorkerError("Input STL failed structural validation.") from exc
    profiles = [
        _regular_file(workdir, name, MAX_PROFILE_BYTES)
        for name in ("printer.json", "filament.json", "process.json")
    ]
    for profile in profiles:
        _check_native_json(profile)
    outdir = workdir / "creality-output"
    if outdir.exists() or outdir.is_symlink():
        raise WorkerError("Creality Print output directory must not exist yet.")
    _output_path(workdir)
    # Verified from upstream Creality Print CLI docs. They use underscores,
    # unlike the hyphenated flags in the Orca adapter.
    return [
        str(binary), "--slice", "0", "--outputdir", str(outdir),
        "--load_settings", str(profiles[0]) + ";" + str(profiles[2]),
        "--load_filaments", str(profiles[1]),
        str(model),
    ]


def run_creality(binary: Path, workdir: Path, *, timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS):
    if not isinstance(timeout_seconds, int) or not 1 <= timeout_seconds <= 900:
        raise WorkerError("Invalid slice timeout.")
    workdir = Path(workdir).resolve(strict=True)
    if not workdir.is_dir():
        raise WorkerError("Worker scratch directory is invalid.")
    command = creality_command(Path(binary), workdir)
    outdir = workdir / "creality-output"
    proc = None
    try:
        proc = subprocess.Popen(
            command, cwd=str(workdir),
            env=slicing_environment(workdir),
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        try:
            proc.communicate(timeout=timeout_seconds)
        except subprocess.TimeoutExpired:
            os.killpg(proc.pid, signal.SIGKILL)
            proc.communicate()
            raise WorkerError("Creality Print did not complete the CLI slice in time.") from None
        if proc.returncode != 0:
            raise WorkerError("Creality Print failed to slice using the selected native profiles.")
        if outdir.is_symlink() or not outdir.is_dir():
            raise WorkerError("Creality Print produced no safe output directory.")
        # CLI builds may emit a log/result JSON in addition to a G-code.
        # Ignore those metadata files, but fail closed on unexpected artifacts.
        outputs = list(outdir.iterdir())
        gcode = [p for p in outputs if p.suffix.lower() == ".gcode"]
        if len(gcode) != 1 or any(p.suffix.lower() not in {".gcode", ".json", ".log", ".txt"}
                                   or p.is_symlink() or not p.is_file() for p in outputs):
            raise WorkerError("Creality Print did not produce exactly one supported G-code artifact.")
        source = gcode[0]
        if not 0 < source.stat().st_size <= MAX_GCODE_BYTES:
            raise WorkerError("Creality Print G-code output is empty or oversized.")
        target = _output_path(workdir)
        with source.open("rb") as src, target.open("xb") as dst:
            while chunk := src.read(65536):
                dst.write(chunk)
                if dst.tell() > MAX_GCODE_BYTES:
                    raise WorkerError("Creality Print output exceeds the G-code limit.")
        if b"\x00" in target.read_bytes()[:4096]:
            raise WorkerError("Creality Print produced unsupported binary G-code.")
        return {"status": "completed", "gcode_path": str(target), "bytes": target.stat().st_size}
    except OSError as exc:
        raise WorkerError("Creality Print worker could not launch the approved binary.") from exc
