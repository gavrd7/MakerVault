"""Creality Print CLI adapter for one explicitly approved binary.

Uses the Creality 7.3.1 tested hyphenated CLI flags. Multi-STL jobs
accept one-based logical material indices and must pass an output tool audit.
The 3MF/painting path remains separately gated until native validation.
"""
import json
import logging
import os
import tempfile
from pathlib import Path
import signal
import subprocess

from .resource_budget import model_input_budget, gcode_output_budget
from .runner import (
    DEFAULT_TIMEOUT_SECONDS, MAX_GCODE_BYTES, MAX_MODEL_BYTES,
    MAX_PROFILE_BYTES, WorkerError, _regular_file, _output_path,
)
from .stl_validation import StlValidationError, validate_stl
from .three_mf_validation import validate_worker_3mf
from .headless_env import slicing_environment
from .orca_runner import NETWORK_KEYS, SCRIPT_KEYS
from .creality_material_cli import (CrealityMaterialRouteError, native_stl_material_arguments)
from .creality_project_validation import validate_creality_project

logger = logging.getLogger(__name__)


def _cli_failure_reason(output):
    """Classify a bounded stderr excerpt without persisting untrusted text."""
    message = output.decode("utf-8", errors="replace").lower()
    if any(term in message for term in ("qt.qpa.plugin", "could not connect to display",
                                        "could not load the qt platform plugin")):
        return "Creality Print CLI could not initialise its headless Qt platform."
    if any(term in message for term in ("error while loading shared libraries",
                                        "cannot open shared object file")):
        return "Creality Print CLI is missing a runtime library."
    if "only one cli command may be specified" in message:
        return "Creality Print CLI received conflicting commands."
    if "no cli command was specified" in message:
        return "Creality Print CLI did not recognise a slicing command."
    if any(term in message for term in ("unknown option", "unrecognized option",
                                        "unrecognised option", "invalid command line",
                                        "invalid option", "unknown argument")):
        return "Creality Print CLI rejected a command-line option."
    if any(term in message for term in ("params in command line error",
                                        "cli parameter parsing failed")):
        return "Creality Print CLI rejected its command-line parameters."
    if any(term in message for term in (
            "error load config from json", "param values in 3mf/config error",
            "invalid project filament nozzle mapping",
            "failed to load project", "cannot parse project")):
        return "Creality Print rejected its embedded 3MF project configuration."
    if any(term in message for term in ("failed to load settings", "failed to load preset",
                                        "invalid preset", "invalid config", "load config failed")):
        return "Creality Print CLI could not load a native preset."
    return "Creality Print failed to slice using the selected native profiles."



def _cli_validation_category(output):
    """Allowlisted topic only, extracted from Creality's validation error.

    The native CLI writes 'got error when validate: <detail>'. Never return
    that detail itself: it may include machine scripts or arbitrary paths.
    """
    text = output.decode("utf-8", errors="replace").lower()
    markers = ("got error when validate:", "validation failed:")
    details = [line.split(marker, 1)[1].strip()
               for line in text.splitlines()[-400:]
               for marker in markers if marker in line]
    if not details:
        return None
    detail = details[-1][:1024]
    categories = (
        (("wipe tower", "prime tower", "purge tower"), "prime-tower"),
        (("layer height", "first layer height"), "layer-height"),
        (("line width", "extrusion width"), "line-width"),
        (("nozzle diameter", "nozzle size"), "nozzle"),
        (("flow ratio", "flowrate", "flow rate"), "flow"),
        (("filament", "temperature"), "filament"),
        (("support", "overhang"), "supports"),
        (("bed", "build plate", "printable area"), "build-plate"),
    )
    for phrases, category in categories:
        if any(phrase in detail for phrase in phrases):
            return category
    return None


def _check_native_json(path):
    """Check native JSON and remove network-only preferences from scratch.

    Installed profile originals are retained untouched in MakerVault storage.
    Native post-processing commands remain prohibited.
    """
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (ValueError, OSError, UnicodeError):
        raise WorkerError("Invalid Creality Print JSON profile.") from None
    if not isinstance(value, dict) or value.get("inherits"):
        raise WorkerError("Creality Print profile requires a self-contained, verified native preset.")
    sanitized = False

    def walk(item, depth=0):
        nonlocal sanitized
        if depth > 12:
            raise WorkerError("Creality Print profile nesting exceeds the limit.")
        if isinstance(item, dict):
            if len(item) > 4096:
                raise WorkerError("Creality Print profile has too many properties.")
            for key in list(item):
                normalized = str(key).strip().lower()
                if normalized in SCRIPT_KEYS:
                    raise WorkerError("Creality Print native profile includes a blocked post-processing command.")
                if normalized in NETWORK_KEYS:
                    del item[key]
                    sanitized = True
                    continue
                walk(item[key], depth + 1)
        elif isinstance(item, list):
            if len(item) > 4096:
                raise WorkerError("Creality Print profile contains too many entries.")
            for child in item:
                walk(child, depth + 1)
    walk(value)
    if sanitized:
        # This is the worker's ephemeral copy, never the imported source.
        path.write_text(json.dumps(value, separators=(",", ":"), ensure_ascii=False),
                        encoding="utf-8")


def creality_command(binary: Path, workdir: Path):
    """Construct fixed arguments without accepting arbitrary client options."""
    if binary.is_symlink() or not binary.is_file() or not os.access(binary, os.X_OK):
        raise WorkerError("Verified Creality Print executable is unavailable.")
    is_project = (workdir / "input.3mf").exists()
    model = _regular_file(workdir, "input.3mf" if is_project else "input.stl", model_input_budget())
    native_project = (workdir / "creality-native-project.marker").exists()
    native_modifiers = (workdir / "native-modifier-project.marker").exists()
    if native_project and native_modifiers:
        raise WorkerError("Conflicting Creality native project contracts.")
    if is_project and native_modifiers:
        from .creality_modifier_validation import validate_creality_modifier_project
        validate_creality_modifier_project(model.read_bytes())
    elif is_project and native_project:
        validate_creality_project(model.read_bytes(), native_tool_count=2)
    elif is_project:
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
    # Creality's config keys use underscores; its CLI flags use hyphens.
    # Multi-STL jobs use 1-based logical filament IDs, never physical tray IDs.
    # The 3MF path must not receive --load-filament-ids.
    command = [
        str(binary), "--cli", "--slice", "0", "--outputdir", str(outdir),
        "--need-gcode-file",
    ]
    if native_project or native_modifiers:
        # Upstream Creality's project loader rejects --load-settings and
        # --load-filaments for 3MF. The project carries its own full config
        # and the CLI skips STL auto-arrangement for project inputs.
        return command + [str(model)]
    command.extend(["--load-settings", str(profiles[0]) + ";" + str(profiles[2])])
    if (workdir / "creality-material-map.json").exists():
        if is_project:
            raise WorkerError("Creality multi-STL material assignments cannot use 3MF.")
        try:
            metadata = json.loads((workdir / "creality-material-map.json").read_text())
            if not isinstance(metadata, dict) or set(metadata) != {"model_count", "tool_ids", "filament_count"}:
                raise ValueError("Invalid material map")
            count = metadata["model_count"]
            if type(count) is not int or not 2 <= count <= 12:
                raise ValueError("Invalid material map count")
            filament_count = metadata["filament_count"]
            if type(filament_count) is not int or not 2 <= filament_count <= 16:
                raise ValueError("Invalid filament palette count")
            filament_files = [workdir / ("filament-" + str(i) + ".json")
                              for i in range(filament_count)]
            if any(not p.is_file() or p.is_symlink() for p in filament_files):
                raise ValueError("Missing contiguous native filament palette")
            models = [workdir / ("input-" + str(i) + ".stl") for i in range(count)]
            for native in filament_files:
                _check_native_json(_regular_file(workdir, native.name, MAX_PROFILE_BYTES))
            for native in models:
                validate_stl(_regular_file(workdir, native.name, model_input_budget()).read_bytes())
            material_args = native_stl_material_arguments(
                models, filament_files, metadata["tool_ids"])
        except (ValueError, KeyError, TypeError, CrealityMaterialRouteError,
                UnicodeDecodeError) as exc:
            raise WorkerError("Invalid native Creality multi-STL filament assignment.") from exc
        command.extend(material_args)
    else:
        command.extend(["--load-filaments", str(profiles[1]), str(model)])
    return command


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
        # Capture both CLI streams: Creality can write startup errors to
        # stdout rather than stderr. Never persist or surface raw output.
        # Temporary file avoids unbounded pipe buffering.
        with tempfile.TemporaryFile(mode="w+b") as diagnostics:
            proc = subprocess.Popen(
                command, cwd=str(workdir),
                env=slicing_environment(workdir),
                stdout=diagnostics, stderr=subprocess.STDOUT,
                start_new_session=True,
            )
            try:
                proc.communicate(timeout=timeout_seconds)
            except subprocess.TimeoutExpired:
                os.killpg(proc.pid, signal.SIGKILL)
                proc.communicate()
                raise WorkerError("Creality Print did not complete the CLI slice in time.") from None
            if proc.returncode != 0:
                # Creality writes the actionable validation message near
                # the end of verbose native startup logs. Capture a bounded
                # tail, not the first 32 KiB. Never persist raw contents.
                diagnostics.seek(0, os.SEEK_END)
                output_size = diagnostics.tell()
                diagnostics.seek(max(0, output_size - 32768), os.SEEK_SET)
                output = diagnostics.read(32768)
                # Creality 7.3.1 defines CLI_INVALID_PARAMS as -2; Linux
                # subprocesses report its low eight bits as exit status 254.
                # This is more precise than assuming native presets failed.
                reason = _cli_failure_reason(output)
                if proc.returncode == 232:
                    # CLI_FILE_VERSION_NOT_SUPPORTED = -24 (POSIX 232).
                    reason = "Creality Print rejected the 3MF project file version."
                elif proc.returncode == 205:
                    # CLI_VALIDATE_ERROR = -51 (POSIX 205). The native error
                    # line may identify a topic; only pass an allowlisted
                    # category, never raw stderr or arbitrary setting values.
                    reason = "Creality Print rejected native 3MF slicing parameters during validation."
                elif proc.returncode == 254 and reason == "Creality Print failed to slice using the selected native profiles.":
                    reason = "Creality Print CLI rejected its command-line parameters."
                logger.warning("Creality Print CLI exited with status %d (%s)",
                               proc.returncode, reason)
                error = WorkerError(reason)
                # A subprocess exit status is non-secret structured data. Do
                # not attach raw stdout, CLI arguments, paths or profile JSON.
                if type(proc.returncode) is int and 1 <= proc.returncode <= 255:
                    error.cli_exit_code = proc.returncode
                if proc.returncode == 205:
                    category = _cli_validation_category(output)
                    if category is not None:
                        error.cli_validation_category = category
                raise error
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
        if not 0 < source.stat().st_size <= gcode_output_budget():
            raise WorkerError("Creality Print G-code output is empty or oversized.")
        target = _output_path(workdir)
        with source.open("rb") as src, target.open("xb") as dst:
            while chunk := src.read(65536):
                dst.write(chunk)
                if dst.tell() > gcode_output_budget():
                    raise WorkerError("Creality Print output exceeds the G-code limit.")
        if b"\x00" in target.read_bytes()[:4096]:
            raise WorkerError("Creality Print produced unsupported binary G-code.")
        return {"status": "completed", "gcode_path": str(target), "bytes": target.stat().st_size}
    except OSError as exc:
        raise WorkerError("Creality Print worker could not launch the approved binary.") from exc
