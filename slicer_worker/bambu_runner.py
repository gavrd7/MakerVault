"""Bambu Studio CLI contract in the isolated MakerVault worker.

Kept separate from Orca's executable runner: shared ancestry does not prove
identical native 3MF output, profile/resource resolution or firmware mapping.
The approved isolated worker must provide a reviewed Bambu executable.
"""
import os
import re
import signal
import stat
import subprocess
import zipfile
from pathlib import Path

from .runner import MAX_GCODE_BYTES, MAX_MODEL_BYTES, MAX_PROFILE_BYTES, DEFAULT_TIMEOUT_SECONDS
from .runner import WorkerError, _regular_file, _output_path
from .orca_runner import _native_json
from .headless_env import slicing_environment
from .stl_validation import StlValidationError, validate_stl
from .three_mf_validation import validate_worker_3mf


def bambu_command(binary: Path, workdir: Path) -> list[str]:
    """Build fixed, documented Bambu CLI flags; no user-selected arguments."""
    binary = Path(binary)
    if not binary.is_file() or not os.access(binary, os.X_OK):
        raise WorkerError("Reviewed Bambu Studio executable is unavailable.")
    if binary.is_symlink():
        # Official AppImage extraction may ship AppRun as a link to an
        # executable inside the same extracted bundle. Never follow a link
        # outside that bundle or accept symlinks under other entrypoint names.
        try:
            target = binary.resolve(strict=True)
            if binary.name != "AppRun" or not target.is_relative_to(binary.parent.resolve(strict=True)):
                raise WorkerError("Bambu Studio executable symlink escapes its bundle.")
        except (OSError, RuntimeError, ValueError) as exc:
            raise WorkerError("Bambu Studio executable symlink is invalid.") from exc
    workdir = Path(workdir).resolve(strict=True)
    stl = workdir / "input.stl"
    three_mf = workdir / "input.3mf"
    if stl.is_file() and not stl.is_symlink() and not three_mf.exists():
        model = _regular_file(workdir, "input.stl", MAX_MODEL_BYTES)
        try:
            validate_stl(model.read_bytes())
        except StlValidationError as exc:
            raise WorkerError("Input STL failed structural validation.") from exc
        is_stl = True
    elif three_mf.is_file() and not three_mf.is_symlink() and not stl.exists():
        model = _regular_file(workdir, "input.3mf", MAX_MODEL_BYTES)
        validate_worker_3mf(model.read_bytes())
        is_stl = False
    else:
        raise WorkerError("Choose exactly one supported STL or 3MF input.")
    printer = _regular_file(workdir, "printer.json", MAX_PROFILE_BYTES)
    process = _regular_file(workdir, "process.json", MAX_PROFILE_BYTES)
    filament = _regular_file(workdir, "filament.json", MAX_PROFILE_BYTES)
    # Bambu upstream explicitly requires *complete* native profiles.
    # Reuse existing scratch-only network-key sanitisation and post-process
    # rejection; never resolve unknown inheritance to arbitrary host files.
    for profile in (printer, process, filament):
        _native_json(profile)
    # Use the exact worker-validated 0-based native filament palette.
    # Bambu CLI accepts a semicolon-separated list of complete native JSON
    # presets; never infer it from a physical AMS/CFS slot index.
    palette = []
    for index in range(16):
        candidate = workdir / ("filament-" + str(index) + ".json")
        if candidate.is_symlink():
            raise WorkerError("Bambu native palette cannot contain links.")
        if not candidate.exists():
            if any((workdir / ("filament-" + str(other) + ".json")).exists()
                   for other in range(index + 1, 16)):
                raise WorkerError("Bambu native palette must be contiguous.")
            break
        palette.append(_regular_file(workdir, candidate.name, MAX_PROFILE_BYTES))
    if palette:
        if is_stl or len(palette) < 2:
            raise WorkerError("Bambu multi-filament slicing requires 3MF and two or more native presets.")
        if palette[0].read_bytes() != filament.read_bytes():
            raise WorkerError("Bambu first native palette preset must match the selected filament.")
        for candidate in palette:
            _native_json(candidate)
    _output_path(workdir)
    output = workdir / "bambu-sliced.3mf"
    if output.exists() or output.is_symlink():
        raise WorkerError("Bambu Studio output already exists.")
    args = [str(binary)]
    if is_stl:
        # The upstream documented STL flow needs a placement arrangement.
        args += ["--arrange", "1"]
    args += [
        "--load-settings", str(printer) + ";" + str(process),
        "--load-filaments", ";".join(str(p) for p in palette) if palette else str(filament),
        "--slice", "0", "--export-3mf", str(output), str(model),
    ]
    return args


def extract_single_bambu_gcode(sliced_project: Path, workdir: Path) -> Path:
    """Extract exactly one bounded plain G-code plate from native sliced 3MF.

    No arbitrary ZIP files or member names are extracted to the filesystem.
    Actual native 2.9.1 output/member layout still requires pinned-binary proof.
    """
    archive = _regular_file(workdir, sliced_project.name, 128 * 1024 * 1024)
    if archive.name != "bambu-sliced.3mf":
        raise WorkerError("Unexpected Bambu output artifact.")
    try:
        with zipfile.ZipFile(archive) as zf:
            if len(zf.infolist()) > 2000:
                raise WorkerError("Bambu native 3MF has too many entries.")
            matches = []
            seen_names = set()
            for info in zf.infolist():
                name = info.filename
                if name in seen_names:
                    raise WorkerError("Bambu native 3MF contains duplicate entries.")
                seen_names.add(name)
                # Reject unrecognized G-code members as well as multiple
                # recognised plates; never silently omit an unexpected toolpath.
                if name.lower().endswith(".gcode") and not re.fullmatch(
                        r"Metadata/plate_[1-9][0-9]*\.gcode", name):
                    raise WorkerError("Bambu native output includes an unexpected G-code plate.")
                if re.fullmatch(r"Metadata/plate_[1-9][0-9]*\.gcode", name):
                    if info.file_size <= 0 or info.file_size > MAX_GCODE_BYTES:
                        raise WorkerError("Bambu G-code exceeds size limits.")
                    if stat.S_IFMT(info.external_attr >> 16) == stat.S_IFLNK:
                        raise WorkerError("Bambu output cannot contain symlink G-code.")
                    matches.append(info)
            if len(matches) != 1:
                raise WorkerError(
                    "Bambu native output must contain exactly one G-code plate.")
            output = _output_path(workdir)
            total = 0
            head = b""
            # Read only one plate in chunks; do not trust ZIP header sizes.
            try:
                with zf.open(matches[0]) as source, output.open("xb") as target:
                    while block := source.read(65536):
                        total += len(block)
                        if total > MAX_GCODE_BYTES:
                            raise WorkerError("Bambu G-code exceeds size limits.")
                        if len(head) < 4096:
                            head += block[:4096 - len(head)]
                        target.write(block)
            except BaseException:
                output.unlink(missing_ok=True)
                raise
    except WorkerError:
        raise
    except (zipfile.BadZipFile, EOFError, OSError, RuntimeError, ValueError) as exc:
        raise WorkerError("Bambu native 3MF output is invalid.") from exc
    if not total or b"\0" in head:
        output.unlink(missing_ok=True)
        raise WorkerError("Bambu generated unsupported binary or empty G-code.")
    return output


def run_bambu(binary: Path, workdir: Path, *, timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS) -> dict:
    """Execute exact approved Bambu Studio in the isolated worker.

    The worker container, not this helper, is responsible for filesystem,
    network, identity and resource isolation. Real Bambu CLI acceptance is
    required before the service may route jobs here.
    """
    if type(timeout_seconds) is not int or not 1 <= timeout_seconds <= 900:
        raise WorkerError("Invalid Bambu slice timeout.")
    workdir = Path(workdir).resolve(strict=True)
    if not workdir.is_dir():
        raise WorkerError("Worker scratch directory is invalid.")
    command = bambu_command(binary, workdir)
    try:
        proc = subprocess.Popen(
            command, cwd=str(workdir),
            env={**slicing_environment(workdir),
                 # Bambu 2.9.x can dereference a missing SSL_CERT_FILE even
                 # in headless/offline CLI startup. This is a fixed public
                 # system CA path, not a network or credential setting.
                 "SSL_CERT_FILE": "/etc/ssl/certs/ca-certificates.crt"},
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        try:
            proc.communicate(timeout=timeout_seconds)
        except subprocess.TimeoutExpired:
            os.killpg(proc.pid, signal.SIGKILL)
            proc.communicate()
            raise WorkerError("Bambu Studio slicing timed out.") from None
        if proc.returncode != 0:
            raise WorkerError("Bambu Studio CLI rejected the native profiles or model.")
        output = extract_single_bambu_gcode(workdir / "bambu-sliced.3mf", workdir)
        return {"status": "completed", "gcode_path": str(output),
                "bytes": output.stat().st_size}
    except OSError as exc:
        raise WorkerError("Isolated worker could not execute Bambu Studio.") from exc
