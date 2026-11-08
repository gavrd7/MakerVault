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
import logging
import threading
from collections import deque

from .stl_validation import StlValidationError, validate_stl
from .three_mf_validation import validate_worker_3mf
from .headless_env import slicing_environment
from .runner import (
    DEFAULT_TIMEOUT_SECONDS, MAX_GCODE_BYTES, MAX_MODEL_BYTES, MAX_PROFILE_BYTES,
    WorkerError, _regular_file, _output_path,
)


# Never execute post-processing commands from imported profiles.
SCRIPT_KEYS = {
    "post_process", "post_process_scripts", "post_processing", "post_processing_scripts",
}
# Official printer profiles can include print-host connection preferences.
# They have no purpose in offline G-code generation. Remove them only from
# the worker's scratch copy, not the saved upstream profile.
NETWORK_KEYS = {
    "print_host", "printhost_apikey", "printhost_password",
    "printhost_authorization_type", "printer_agent", "print_host_webui",
    "printhost_ssl_ignore_revoke",
}
FORBIDDEN_KEYS = SCRIPT_KEYS | NETWORK_KEYS

logger = logging.getLogger(__name__)

def _engine_exit_reason(stderr):
    """Classify diagnostics without exposing private file paths or profile data."""
    message = stderr.decode("utf-8", errors="replace").lower()
    if any(term in message for term in (
        "qt.qpa.plugin", "could not load the qt platform plugin",
        "could not connect to display", "no qt platform plugin",
    )):
        return "qt-platform-failed"
    if any(term in message for term in (
        "error while loading shared libraries", "cannot open shared object file",
        "library not found",
    )):
        return "missing-runtime-library"
    if any(term in message for term in (
        "appimage", "squashfs", "fuse", "failed to extract",
    )):
        return "appimage-runtime-failed"
    if any(term in message for term in (
        "unrecognized option", "unknown option", "invalid command line",
        "unrecognized argument",
    )):
        return "unsupported-cli-option"
    if any(term in message for term in (
        "param values in 3mf/config error", "not in range",
    )):
        return "native-project-settings-invalid"
    if any(term in message for term in (
        "failed to load 3mf", "invalid 3mf", "3mf import failed",
    )):
        return "native-project-load-failed"
    if any(term in message for term in (
        "invalid config", "invalid configuration", "invalid preset",
        "invalid profile", "failed to load config", "failed to load settings",
    )):
        return "native-profile-load-failed"
    return "engine-exited"


def _bounded_stderr(stream, tail, limit=8192):
    """Drain the child pipe without allowing output to grow in memory."""
    try:
        while chunk := stream.read(4096):
            tail.append(chunk)
            total = sum(len(part) for part in tail)
            while total > limit and tail:
                first = tail.popleft()
                total -= len(first)
                if total < limit:
                    tail.appendleft(first[-(limit - total):])
                    break
    finally:
        stream.close()


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
    sanitized = False
    def check(node, depth=0):
        nonlocal sanitized
        if depth > 12:
            raise WorkerError("Native Orca profile nesting exceeds its limit.")
        if isinstance(node, dict):
            for key in list(node):
                normalized = str(key).strip().lower()
                if normalized in SCRIPT_KEYS:
                    raise WorkerError("Unsafe Orca profile command or network setting.")
                if normalized in NETWORK_KEYS:
                    del node[key]
                    sanitized = True
                    continue
                check(node[key], depth + 1)
        elif isinstance(node, list):
            if len(node) > 4096:
                raise WorkerError("Native Orca profile contains too many entries.")
            for item in node:
                check(item, depth + 1)
    check(value)
    if sanitized:
        # The source exists only in an isolated ephemeral worker directory.
        # Never alter MakerVault's original encrypted profile.
        path.write_text(json.dumps(value, ensure_ascii=False, separators=(",", ":")),
                        encoding="utf-8")


def _execution_binary(binary: Path):
    """Use the extracted, image-pinned AppRun instead of AppImage/FUSE.

    The registry verifies the unchanged official AppImage SHA-256. Its extracted
    AppDir is baked into the same immutable Docker image at build time. Never
    execute an AppImage from the per-job scratch directory or extract one during
    a request.
    """
    if binary.suffix.lower() != ".appimage":
        return binary
    appdir = binary.parent / "squashfs-root"
    entry = appdir / "AppRun"
    if appdir.is_symlink() or not appdir.is_dir() or not entry.exists():
        raise WorkerError("Pinned OrcaSlicer AppImage has no extracted runtime.")
    resolved_dir = appdir.resolve(strict=True)
    resolved_entry = entry.resolve(strict=True)
    if (not resolved_entry.is_relative_to(resolved_dir)
            or not resolved_entry.is_file() or not os.access(resolved_entry, os.X_OK)):
        raise WorkerError("Pinned OrcaSlicer extracted runtime is unsafe or unavailable.")
    return entry


def orca_command(binary: Path, workdir: Path):
    """Fixed single-model, single-plate slicing command."""
    if binary.is_symlink() or not binary.is_file() or not os.access(binary, os.X_OK):
        raise WorkerError("Approved OrcaSlicer binary is unavailable.")
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
    for item in profiles:
        _native_json(item)
    outdir = workdir / "orca-output"
    if outdir.exists() or outdir.is_symlink():
        raise WorkerError("Output directory is not empty; fresh scratch is required.")
    _output_path(workdir)
    executable = _execution_binary(binary)
    return [
        str(executable), str(model), "--load-settings",
        str(profiles[2]) + ";" + str(profiles[0]),
        "--load-filaments", str(profiles[1]),
        "--load-defaultfila",
        *(["--arrange", "1"] if not is_project else []),
        "--slice", "1",
        "--mtcpp", "500000", "--mstpp", "300",
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
            env=slicing_environment(workdir),
            stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, start_new_session=True,
        )
        # Drain stderr in parallel so a chatty CLI cannot deadlock. Retain a
        # small diagnostic tail but never log the raw text or any private paths.
        tail = deque()
        reader = None
        if getattr(proc, "stderr", None) is not None:
            reader = threading.Thread(target=_bounded_stderr, args=(proc.stderr, tail), daemon=True)
            reader.start()
        try:
            proc.communicate(timeout=timeout_seconds) if reader is None else proc.wait(timeout=timeout_seconds)
        except subprocess.TimeoutExpired:
            os.killpg(proc.pid, signal.SIGKILL)
            proc.wait()
            if reader is not None:
                reader.join(timeout=2)
            raise WorkerError("Slicing timed out.") from None
        if reader is not None:
            reader.join(timeout=2)
        if proc.returncode != 0:
            reason = _engine_exit_reason(b"".join(tail))
            # Orca's CLI uses 238 for some project/config validation exits.
            # Preserve this as a diagnostic class, not a claim about the cause.
            if reason == "engine-exited" and proc.returncode == 238:
                reason = "cli-validation-exit-238"
            # Reason and exit status are bounded diagnostics, not CLI output.
            logger.warning("OrcaSlicer subprocess ended: exit=%s category=%s", proc.returncode, reason)
            raise WorkerError("OrcaSlicer CLI exited: " + reason + ".")
        outdir = workdir / "orca-output"
        if outdir.is_symlink() or not outdir.is_dir():
            raise WorkerError("OrcaSlicer produced no safe output directory.")
        outputs = list(outdir.iterdir())
        # Official Orca CLI releases can emit result.json or statistics next
        # to plate_1.gcode. They are metadata, not a second sliced plate.
        # Keep strict rejection of unknown, nested or linked artifacts.
        gcode = [p for p in outputs if p.suffix.lower() == ".gcode"]
        allowed_metadata = {"result.json"}
        if (len(gcode) != 1 or len(outputs) > 4 or
                any(p.is_symlink() or not p.is_file() or
                    (p.suffix.lower() != ".gcode" and
                     p.name not in allowed_metadata and
                     not p.name.endswith(".statistics.json"))
                    for p in outputs)):
            raise WorkerError("OrcaSlicer must produce exactly one G-code plate and only expected metadata.")
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
