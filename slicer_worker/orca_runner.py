"""Candidate OrcaSlicer worker adapter; not an approved engine installation.

The CLI argument structure follows upstream Orca's documented --slice,
--load-settings, --load-filaments and --outputdir options. Each exact binary
version and produced G-code still needs independent real fixture validation.
"""
import json
import os
from pathlib import Path
import signal
import subprocess

from .stl_validation import StlValidationError, validate_stl
from .runner import (
    DEFAULT_TIMEOUT_SECONDS, MAX_GCODE_BYTES, MAX_MODEL_BYTES, MAX_PROFILE_BYTES,
    WorkerError, _regular_file, _output_path,
)


FORBIDDEN_KEYS = {
    "post_process", "post_process_scripts", "post_processing", "post_processing_scripts",
    "print_host", "printhost_apikey", "printhost_password", "printhost_authorization_type",
    "printer_agent", "print_host_webui", "printhost_ssl_ignore_revoke",
}


def _native_json(path):
    try:
        text = path.read_text(encoding="utf-8-sig")
        value = json.loads(text)
    except (ValueError, OSError, UnicodeError):
        raise WorkerError("Invalid native Orca JSON profile.") from None
    if not isinstance(value, dict):
        raise WorkerError("Orca profile must be a JSON object.")
    # Orca system/user profiles commonly inherit missing machine and material
    # settings. A worker with only three staged files cannot safely resolve
    # external parents, so do not silently substitute defaults.
    if value.get("inherits"):
        raise WorkerError("Orca profile requires an unbundled parent preset; use a verified complete native profile bundle.")
    def check(node, depth=0):
        if depth > 12:
            raise WorkerError("Native Orca profile nesting exceeds its limit.")
        if isinstance(node, dict):
            for key, item in node.items():
                if str(key).strip().lower() in FORBIDDEN_KEYS:
                    raise WorkerError("Unsafe Orca profile command or network setting.")
                check(item, depth + 1)
        elif isinstance(node, list):
            if len(node) > 4096:
                raise WorkerError("Native Orca profile contains too many entries.")
            for item in node:
                check(item, depth + 1)
    check(value)


def orca_command(binary: Path, workdir: Path):
    """Fixed single-model, single-plate slicing command."""
    if binary.is_symlink() or not binary.is_file() or not os.access(binary, os.X_OK):
        raise WorkerError("Approved OrcaSlicer binary is unavailable.")
    model = _regular_file(workdir, "input.stl", MAX_MODEL_BYTES)
    try:
        validate_stl(model.read_bytes())
    except StlValidationError as exc:
        raise WorkerError("Input STL failed structural validation.") from exc
    profiles = [
        _regular_file(workdir, name, MAX_PROFILE_BYTES)
        for name in ("printer.json", "filament.json", "process.json")
    ]
    for item in profiles:
        _native_json(item)
    outdir = workdir / "orca-output"
    if outdir.exists() or outdir.is_symlink():
        raise WorkerError("Output directory is not empty; fresh scratch is required.")
    _output_path(workdir)
    return [
        str(binary), str(model), "--load-settings",
        str(profiles[0]) + ";" + str(profiles[2]),
        "--load-filaments", str(profiles[1]),
        "--arrange", "1", "--slice", "1",
        "--outputdir", str(outdir),
    ]


def run_orca(binary: Path, workdir: Path, *, timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS):
    """Run the proposed Orca integration inside an already isolated worker."""
    if not isinstance(timeout_seconds, int) or not 1 <= timeout_seconds <= 900:
        raise WorkerError("Invalid slice timeout.")
    workdir = Path(workdir).resolve(strict=True)
    if not workdir.is_dir():
        raise WorkerError("Worker scratch directory is invalid.")
    command = orca_command(Path(binary), workdir)
    try:
        proc = subprocess.Popen(
            command, cwd=str(workdir),
            env={"HOME": str(workdir), "TMPDIR": str(workdir), "LANG": "C.UTF-8",
                 "LC_ALL": "C.UTF-8", "PATH": "/usr/bin:/bin"},
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True,
        )
        try:
            proc.communicate(timeout=timeout_seconds)
        except subprocess.TimeoutExpired:
            os.killpg(proc.pid, signal.SIGKILL)
            proc.communicate()
            raise WorkerError("Slicing timed out.") from None
        if proc.returncode != 0:
            raise WorkerError("OrcaSlicer failed. Check the engine-native profiles.")
        outdir = workdir / "orca-output"
        if outdir.is_symlink() or not outdir.is_dir():
            raise WorkerError("OrcaSlicer produced no safe output directory.")
        outputs = list(outdir.iterdir())
        gcode = [p for p in outputs if p.suffix.lower() == ".gcode"]
        if len(outputs) != 1 or len(gcode) != 1:
            raise WorkerError("OrcaSlicer must produce exactly one plain-text G-code file.")
        source = gcode[0]
        if source.is_symlink() or not source.is_file() or not 0 < source.stat().st_size <= MAX_GCODE_BYTES:
            raise WorkerError("OrcaSlicer output is missing or exceeds its limit.")
        target = _output_path(workdir)
        with source.open("rb") as src, target.open("xb") as dst:
            while chunk := src.read(65536):
                dst.write(chunk)
                if dst.tell() > MAX_GCODE_BYTES:
                    raise WorkerError("G-code exceeded size limit.")
        with target.open("rb") as stream:
            if b"\x00" in stream.read(4096):
                raise WorkerError("OrcaSlicer produced unsupported binary G-code.")
        return {"status": "completed", "gcode_path": str(target), "bytes": target.stat().st_size}
    except OSError as exc:
        raise WorkerError("Isolated worker could not run OrcaSlicer.") from exc
